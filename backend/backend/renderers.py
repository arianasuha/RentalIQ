from rest_framework.renderers import JSONRenderer as JsonRenderer

class ViewRenderer(JsonRenderer):
    charset = 'utf-8'
    pass