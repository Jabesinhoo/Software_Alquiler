# error_views.py
from django.shortcuts import render
from django.template import loader
from django.http import HttpResponseForbidden, HttpResponseNotFound, HttpResponseServerError


def handler403(request, exception=None):
    """Vista personalizada para error 403 - Prohibido"""
    context = {
        'error_code': '403',
        'error_title': 'Acceso Prohibido',
        'error_message': 'No tienes permiso para acceder a esta página.'
    }
    template = loader.get_template('errors/error.html')
    return HttpResponseForbidden(template.render(context, request))

def handler404(request, exception=None):
    """Vista personalizada para error 404 - No encontrado"""
    context = {
        'error_code': '404',
        'error_title': 'Página no encontrada',
        'error_message': 'La página que buscas no existe o ha sido movida.'
    }
    template = loader.get_template('errors/error.html')
    return HttpResponseNotFound(template.render(context, request))

def handler500(request):
    """Vista personalizada para error 500 - Error del servidor"""
    context = {
        'error_code': '500',
        'error_title': 'Error del servidor',
        'error_message': 'Algo salió mal en nuestro servidor. Estamos trabajando para solucionarlo.'
    }
    template = loader.get_template('errors/error.html')
    return HttpResponseServerError(template.render(context, request))