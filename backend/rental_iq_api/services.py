"""
Business logic and atomic operations for RentIQ financial & escrow workflows.
"""
from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from core_db.models import (
    Rental, 
    RentalWallet, 
    EscrowTransaction, 
    ExtensionRequest, 
    RentalRequest
)


@transaction.atomic
def hold_rental_escrow(rental_id: int, idempotency_key: str = None) -> EscrowTransaction:
    """
    Deducts the total rental fee + deposit from the rentee's wallet balance
    and creates a HELD EscrowTransaction record atomically.
    """
    # 1. Idempotency Check: Prevent duplicate escrow holds
    if idempotency_key and EscrowTransaction.objects.filter(idempotency_key=idempotency_key).exists():
        return EscrowTransaction.objects.get(idempotency_key=idempotency_key)

    # 2. Lock the Rental record
    rental = Rental.objects.select_for_update().get(id=rental_id)
    renter = rental.rental_request.renter

    # 3. Lock Renter's Wallet record to prevent race conditions / double-spending
    wallet, _ = RentalWallet.objects.select_for_update().get_or_create(user=renter)

    total_amount = rental.rental_request.total_rent_amount + rental.rental_request.deposit_amount_snapshot

    if wallet.balance < total_amount:
        raise ValidationError(
            f"Insufficient wallet balance. Required: ৳{total_amount}, Available: ৳{wallet.balance}"
        )

    # 4. Transfer funds from balance to held_deposit
    wallet.balance -= total_amount
    wallet.held_deposit += total_amount
    wallet.save()

    # 5. Create Escrow Ledger Entry
    escrow = EscrowTransaction.objects.create(
        rental=rental,
        transaction_type=EscrowTransaction.TransactionType.HOLD,
        amount=total_amount,
        status=EscrowTransaction.Status.COMPLETED,
        idempotency_key=idempotency_key,
        note=f"Escrow hold for Rental #{rental.id}"
    )

    rental.payment_status = Rental.PaymentStatus.PAID
    rental.status = Rental.RentalStatus.ACTIVE
    rental.save()

    return escrow


@transaction.atomic
def release_escrow_to_owner(rental_id: int) -> EscrowTransaction:
    """
    Executed when an item is safely returned on time.
    Releases base rent to the owner, refunds the deposit to the rentee.
    """
    rental = Rental.objects.select_for_update().get(id=rental_id)
    owner = rental.rental_request.equipment.owner
    renter = rental.rental_request.renter

    owner_wallet, _ = RentalWallet.objects.select_for_update().get_or_create(user=owner)
    renter_wallet, _ = RentalWallet.objects.select_for_update().get_or_create(user=renter)

    rent_amount = rental.rental_request.total_rent_amount
    deposit_amount = rental.rental_request.deposit_amount_snapshot
    total_held = rent_amount + deposit_amount

    # Release rent amount to owner
    owner_wallet.balance += rent_amount
    owner_wallet.save()

    # Deduct total from held_deposit and return security deposit to rentee's available balance
    renter_wallet.held_deposit -= total_held
    renter_wallet.balance += deposit_amount
    renter_wallet.save()

    # Record settlement transaction
    escrow = EscrowTransaction.objects.create(
        rental=rental,
        transaction_type=EscrowTransaction.TransactionType.RELEASE,
        amount=rent_amount,
        status=EscrowTransaction.Status.COMPLETED,
        note=f"Released ৳{rent_amount} to owner {owner.email}. Deposit ৳{deposit_amount} returned to rentee."
    )

    rental.status = Rental.RentalStatus.RETURNED
    rental.deposit_returned = True
    rental.actual_return_date = timezone.now().date()
    rental.save()

    return escrow


@transaction.atomic
def apply_late_penalty(rental_id: int, penalty_amount: Decimal, reason: str = "Overdue return penalty") -> EscrowTransaction:
    """
    Deducts a penalty directly from the rentee's held security deposit 
    and credits it to the owner's available balance.
    """
    rental = Rental.objects.select_for_update().get(id=rental_id)
    owner = rental.rental_request.equipment.owner
    renter = rental.rental_request.renter

    renter_wallet = RentalWallet.objects.select_for_update().get(user=renter)
    owner_wallet, _ = RentalWallet.objects.select_for_update().get_or_create(user=owner)

    if renter_wallet.held_deposit < penalty_amount:
        penalty_amount = renter_wallet.held_deposit  # Cap at remaining deposit

    renter_wallet.held_deposit -= penalty_amount
    owner_wallet.balance += penalty_amount

    renter_wallet.save()
    owner_wallet.save()

    escrow = EscrowTransaction.objects.create(
        rental=rental,
        transaction_type=EscrowTransaction.TransactionType.PENALTY,
        amount=penalty_amount,
        status=EscrowTransaction.Status.COMPLETED,
        note=reason
    )

    rental.status = Rental.RentalStatus.OVERDUE
    rental.save()

    return escrow


@transaction.atomic
def approve_extension_request(extension_id: int) -> ExtensionRequest:
    """
    Approves an extension request, updates the rental request end date, 
    and recalculates total rent.
    """
    ext = ExtensionRequest.objects.select_for_update().get(id=extension_id)
    rental_request = RentalRequest.objects.select_for_update().get(id=ext.rental.rental_request_id)

    if ext.status != ExtensionRequest.Status.PENDING:
        raise ValidationError("Extension request has already been processed.")

    ext.status = ExtensionRequest.Status.APPROVED
    ext.save()

    # Extend end date and recalculate total rent
    rental_request.end_date = ext.proposed_end_date
    rental_request.save()  # Triggers total_rent_amount recalculation in save()

    return ext