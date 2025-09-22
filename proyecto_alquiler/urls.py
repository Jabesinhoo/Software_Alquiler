from django.urls import path, include, register_converter
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse
from django.views.generic import RedirectView
from django.shortcuts import redirect
import uuid # Importar el módulo uuid

# Tu importación de vistas
from alquiler.views.error_views import handler403, handler404, handler500

from alquiler.views.equipo_views import (
    listar_equipos, crear_equipo, editar_equipo, detalle_equipo,
    equipos_disponibles, cambiar_estado_equipo, equipos_por_estado,
    equipos_mas_alquilados, dashboard_admin,
    actualizar_estados_masivo, exportar_equipos_csv,
    historial_equipo, proxima_disponibilidad,
    ejecutar_alertas_vencimiento, eliminar_equipo, pagos_pendientes_admin
)
from alquiler.views.cliente_views import (
listar_clientes, crear_cliente, editar_cliente, detalle_cliente,
cambiar_estado_verificacion, bloquear_cliente,clientes_morosos,validar_documentos_cliente,
registrar_pago_parcial

)

from alquiler.views.alquiler_views import (
listar_alquileres,crear_alquiler,finalizar_alquiler, renovar_alquiler,
generar_acta_entrega, aprobar_alquiler,calendario_alquileres,
detalle_alquiler, cancelar_alquiler,reservar_alquiler,generar_acta_devolucion, crear_contrato, firmar_contrato,
renovar_contrato,eliminar_alquiler, series_disponibles, editar_alquiler, alquileres_a_vencer
)

from alquiler.views.pago_views import (
    RegistrarPagoView,
    PagosPendientesView, GenerarFacturaView, PasarelaPagoView, PagosAlquilerView, RegistrarPagoParcialView,
    PagoDetalleView,ProcesarPagoPasarelaView, TotalPagadoAlquilerView, listar_pagos, editar_pago,verificar_estado_pago_alquiler, enviar_notificacion_pago,
    registrar_pago, detalle_pago,generar_factura_pdf, pagos_vencidos, pagos_proximos_vencer, cambiar_estado_pago, eliminar_pago, reportes_pagos, pagos_parciales, 
)

from alquiler.views.usuario_views import(
    registro_usuario,salir_sesion,asignar_rol, inicio_sesion, pagina_principal, lista_usuarios,editar_usuario,eliminar_usuario,cambiar_estado_usuario,
    cambiar_contrasena, confirmar_eliminar_usuario, detalle_usuario, auditoria_usuario, activar_cuenta,crear_rol,lista_roles,editar_rol,eliminar_rol

)

from alquiler.views.base_views import(
    BusquedaGlobalView, sugerencias_busqueda
)



core_patterns = [
    path('admin/', admin.site.urls),
    #Buscador
    path('buscar/', BusquedaGlobalView.as_view(), name='busqueda_global'),
    path('buscar/sugerencias/', sugerencias_busqueda, name='sugerencias_busqueda'),

    # Urls de Equipos 
    path('equipos/', listar_equipos, name='listar_equipos'),
    path('equipos/nuevo/', crear_equipo, name='crear_equipo'),
    path('equipos/<uuid:id>/', detalle_equipo, name='detalle_equipo'),
    path('equipos/<uuid:id>/editar/', editar_equipo, name='editar_equipo'),
    path('equipos/<uuid:pk>/eliminar/', eliminar_equipo, name='eliminar_equipo'),
    path('equipos-disponibles/', equipos_disponibles, name='equipos_disponibles'),
    path('equipos/<uuid:id>/estado/<str:nuevo_estado>/', cambiar_estado_equipo, name='cambiar_estado_equipo'),
    path('equipos/estado/<str:estado>/', equipos_por_estado, name='equipos_por_estado'),
    path('equipos/estadisticas/', equipos_mas_alquilados, name='equipos_mas_alquilados'),
    path('equipos/exportar-csv/', exportar_equipos_csv, name='exportar_equipos_csv'),
    path('equipos/<uuid:id>/historial/', historial_equipo, name='historial_equipo'),
    path('dashboard/', dashboard_admin, name='dashboard_admin'),
    path('equipos/actualizar-masivo/', actualizar_estados_masivo, name='actualizar_estados_masivo'),
    path('equipos/<uuid:id>/proxima-disponibilidad/', proxima_disponibilidad, name='proxima_disponibilidad'),
    path('pagos/pendientes/', pagos_pendientes_admin, name='pagos_pendientes_admin'),
    path('alertas/vencimiento/manual/', ejecutar_alertas_vencimiento, name='enviar_alertas_vencimiento'),
    path('alquileres/a-vencer/', alquileres_a_vencer, name='alquileres_a_vencer'),

    #Urls clientes 
    path('clientes/', listar_clientes, name='listar_clientes'),
    path('clientes/crear/', crear_cliente, name='crear_cliente'),
    path('clientes/<uuid:id>/editar/', editar_cliente, name='editar_cliente'),
    path('clientes/<uuid:id>/', detalle_cliente, name='detalle_cliente'),
    path('clientes/<uuid:id>/verificar/<str:nuevo_estado>/', cambiar_estado_verificacion, name='cambiar_estado_verificacion'),
    path('clientes/<uuid:id>/bloquear/',bloquear_cliente, name='bloquear_cliente'),
    path('clientes-morosos/', clientes_morosos, name='clientes_morosos'),
    path('clientes/<uuid:id>/validar-documentos/', validar_documentos_cliente, name='validar_documentos_cliente'),

    #Urls Alquileres 
    path('alquiler/<uuid:id_alquiler>/pago-parcial/', registrar_pago_parcial, name='registrar_pago_parcial'),
    path('alquileres/', listar_alquileres, name='listar_alquileres'),
    path('alquileres/crear/', crear_alquiler, name='crear_alquiler'),

    path('equipos/<uuid:equipo_id>/series-disponibles/', series_disponibles, name='series_disponibles'),
    path('alquileres/<uuid:id>/finalizar/', finalizar_alquiler, name='finalizar_alquiler'),
    path('alquileres/reservar/', reservar_alquiler, name='reservar_alquiler'),
    path('alquileres/<uuid:id>/cancelar/', cancelar_alquiler, name='cancelar_alquiler'),
    path('alquileres/<uuid:id>/aprobar/', aprobar_alquiler, name='aprobar_alquiler'),
    path('alquileres/<uuid:id>/renovar/', renovar_alquiler, name='renovar_alquiler'),
    path('alquileres/<uuid:id>/detalle/', detalle_alquiler, name='detalle_alquiler'),
    path('alquileres/calendario/', calendario_alquileres, name='calendario_alquileres'),
    path('alquileres/<uuid:id>/editar/', editar_alquiler, name='editar_alquiler'),
    path('alquileres/<uuid:id>/firmar-contrato/', firmar_contrato, name='firmar_contrato'),
    path('alquileres/<uuid:id>/renovar-contrato/', renovar_contrato, name='renovar_contrato'),
    path('alquileres/<uuid:id>/eliminar/', eliminar_alquiler, name='eliminar_alquiler'),
    #incompletas
    path('alquileres/<uuid:id>/acta-entrega/', generar_acta_entrega, name='generar_acta_entrega'),
    path('alquileres/<uuid:id>/acta-devolucion/', generar_acta_devolucion, name='generar_acta_devolucion'),
    path('alquileres/<uuid:id>/crear-contrato/', crear_contrato, name='crear_contrato'),

    #Pagos 
    path('pagos/', listar_pagos, name='lista_pagos'),
    path('pagos/registrar/', registrar_pago, name='registrar_pago'),
    path('pagos/<uuid:pago_uuid>/', detalle_pago, name='detalle_pago'),
    path('pagos/<uuid:pago_uuid>/editar/', editar_pago, name='editar_pago'),
    path('pagos/<uuid:pago_uuid>/factura/', generar_factura_pdf, name='generar_factura_pdf'),
    path('pagos/<uuid:pago_uuid>/cambiar-estado/<str:nuevo_estado>/', cambiar_estado_pago, name='cambiar_estado_pago'),
    path('pagos/<uuid:pago_uuid>/eliminar/', eliminar_pago, name='eliminar_pago'),
    path('pagos/reportes/', reportes_pagos, name='reportes_pagos'),
    path('pagos/vencidos/', pagos_vencidos, name='pagos_vencidos'),
    path('pagos/proximos/', pagos_proximos_vencer, name='pagos_proximos'),

    path('pagos/parcial/', pagos_parciales, name='pagos_parciales'),  # Versión con GET
    path('alquiler/<uuid:alquiler_uuid>/pago-parcial/', registrar_pago_parcial, name='registrar_pago_parcial_alquiler'),  # Con alquiler directo en URL



    #Urls Usuario 
    path('', inicio_sesion, name='inicio_sesion'),
    path('registro/', registro_usuario, name='registro'),
    path('salir/', salir_sesion, name='salir'),
    path('inicio/', pagina_principal, name='pagina_principal'),
    path('usuarios/', lista_usuarios, name='lista_usuarios'),
    path('usuarios/editar/<uuid:usuario_uuid>/', editar_usuario, name='editar_usuario'),
    path('usuarios/<uuid:usuario_uuid>/asignar-rol/', asignar_rol, name='asignar_rol'),
    path('usuarios/cambiar-estado/<uuid:usuario_uuid>/', cambiar_estado_usuario, name='cambiar_estado_usuario'),
    path('usuarios/cambiar-contrasena/<uuid:usuario_uuid>/', cambiar_contrasena, name='cambiar_contrasena'),
    path('usuarios/eliminar/<uuid:usuario_uuid>/', confirmar_eliminar_usuario, name='confirmar_eliminar_usuario'),
    path('usuarios/eliminar-confirmado/<uuid:usuario_uuid>/', eliminar_usuario, name='eliminar_usuario'),
    path('usuarios/detalle/<uuid:usuario_uuid>/', detalle_usuario, name='detalle_usuario'),
    path('usuarios/auditoria/<uuid:usuario_uuid>/', auditoria_usuario, name='auditoria_usuario'),
    path('activar/<uidb64>/<token>/', activar_cuenta, name='activar_cuenta'),

    path('roles/', lista_roles, name='lista_roles'),
    path('roles/crear/', crear_rol, name='crear_rol'),
    path('roles/editar/<uuid:rol_uuid>/', editar_rol, name='editar_rol'),
    path('roles/eliminar/<uuid:rol_uuid>/', eliminar_rol, name='eliminar_rol'),

    path('usuarios/<uuid:usuario_id>/asignar-rol/', asignar_rol, name='asignar_rol'),
]


urlpatterns = [
    path('', RedirectView.as_view(url='/guanabanazo/')),
    path('guanabanazo/admin/', admin.site.urls),

    path('guanabanazo/', include((core_patterns, 'alquiler'), namespace='alquiler')),
]


if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler403 = 'alquiler.views.error_views.handler403'
handler404 = 'alquiler.views.error_views.handler404'
handler500 = 'alquiler.views.error_views.handler500'