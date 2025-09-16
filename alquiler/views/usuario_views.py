from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required, permission_required
from ..forms.usuario_forms import RegistroForm,UsuarioEditForm,CambiarContrasenaForm, RolForm
from ..models import Rol, Usuario, UserAuditLog
from django.contrib.auth import login
from django.db.models import Count
from datetime import datetime, timedelta
from django.utils import timezone
from django.db.models.functions import TruncMonth
from django.db.models import Q
from django.views.decorators.http import require_GET
import json
import csv
from django.http import JsonResponse
from django.utils.crypto import get_random_string
from django.core.mail import send_mail
from django.utils.crypto import get_random_string
from django.contrib.sites.shortcuts import get_current_site
from django.template.loader import render_to_string
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_protect
from django.db.models import Max
from django.contrib.auth.hashers import make_password
from django.utils.http import urlsafe_base64_decode
from django.utils.encoding import force_str
from django.contrib.auth import update_session_auth_hash
from django.shortcuts import render, redirect, get_object_or_404
from django.core.paginator import Paginator
from django.conf import settings
from django.http import HttpResponse
from django.urls import reverse
from django.db import transaction

import logging

logger = logging.getLogger(__name__)


def registro_usuario(request):
    if request.method == 'POST':
        form = RegistroForm(request.POST)
        if form.is_valid():
            # Crear usuario inactivo
            usuario = Usuario(
                nombre_usuario=form.cleaned_data['nombre_usuario'],
                is_active=False
            )
            usuario.set_password(form.cleaned_data['password1'])
            usuario.save()

            # Generar y guardar token de activación con marca de tiempo
            token = get_random_string(50)
            usuario.activation_token = token
            usuario.activation_token_created = timezone.now()  # ⏰ Marca de tiempo
            usuario.save()

            # Preparar correo
            current_site = get_current_site(request)
            mail_subject = 'Activa tu cuenta en nuestro sitio'

            html_message = render_to_string('emails/activacion_usuario.html', {
                'user': usuario,
                'domain': current_site.domain,
                'uid': urlsafe_base64_encode(force_bytes(usuario.pk)),
                'token': token,
            })
            activation_url = request.build_absolute_uri(
    reverse('alquiler:activar_cuenta', kwargs={
        'uidb64': urlsafe_base64_encode(force_bytes(usuario.pk)),
        'token': token
    })
)
            plain_message = f"""
Nuevo usuario registrado: {usuario.nombre_usuario}
Activa su cuenta aquí:
{activation_url}
"""

            # Enviar correo al administrador
            send_mail(
                subject=mail_subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[settings.EMAIL_HOST_USER],
                fail_silently=False,
                html_message=html_message
            )

            messages.success(request, '¡Registro exitoso! Por favor revisa tu correo para activar la cuenta desde el panel de administración.')
            return redirect('alquiler:inicio_sesion')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        form = RegistroForm()

    return render(request, 'inicio_sesion.html', {
        'form_type': 'registro',
        'form': form
    })


def activar_cuenta(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        usuario = Usuario.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, Usuario.DoesNotExist):
        usuario = None

    if usuario is not None and usuario.activation_token == token:
        # Validar si el token no ha expirado
        tiempo_limite = usuario.activation_token_created + timedelta(minutes=10)
        if timezone.now() <= tiempo_limite:
            usuario.is_active = True
            usuario.activation_token = None
            usuario.activation_token_created = None
            usuario.save()
            
            # Respuesta simple para el admin sin redirección
            return HttpResponse("""
                <div style="font-family: Arial, sans-serif; text-align: center; padding: 50px; background-color: #f0f8ff;">
                    <div style="background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); display: inline-block;">
                        <h2 style="color: #28a745; margin-bottom: 15px;">✅ Cuenta Activada Exitosamente</h2>
                        <p style="color: #333; font-size: 16px;">El usuario <strong>{}</strong> ha sido activado correctamente.</p>
                        <p style="color: #666; font-size: 14px; margin-top: 20px;">Puedes cerrar esta pestaña.</p>
                    </div>
                </div>
            """.format(usuario.nombre_usuario))
        else:
            return HttpResponse("""
                <div style="font-family: Arial, sans-serif; text-align: center; padding: 50px; background-color: #fff5f5;">
                    <div style="background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); display: inline-block;">
                        <h2 style="color: #dc3545; margin-bottom: 15px;">⏰ Enlace Expirado</h2>
                        <p style="color: #333; font-size: 16px;">El enlace de activación ha expirado.</p>
                        <p style="color: #666; font-size: 14px; margin-top: 20px;">Contacta al usuario para que se registre nuevamente.</p>
                    </div>
                </div>
            """)
    else:
        return HttpResponse("""
            <div style="font-family: Arial, sans-serif; text-align: center; padding: 50px; background-color: #fff5f5;">
                <div style="background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); display: inline-block;">
                    <h2 style="color: #dc3545; margin-bottom: 15px;">❌ Enlace Inválido</h2>
                    <p style="color: #333; font-size: 16px;">El enlace de activación es inválido.</p>
                    <p style="color: #666; font-size: 14px; margin-top: 20px;">Verifica que el enlace esté completo y correcto.</p>
                </div>
            </div>
        """)

def inicio_sesion(request):
    if request.user.is_authenticated:
        return redirect('alquiler:pagina_principal')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            messages.success(request, f'Bienvenido {user.nombre_usuario}')
            return redirect('alquiler:pagina_principal')
        else:
            messages.error(request, 'Usuario o contraseña incorrectos')
    
    return render(request, 'inicio_sesion.html', {
        'form_type': 'inicio',
        'authenticated': False
    })

@login_required
def pagina_principal(request):
    return render(request, 'inicio.html', {
        'user': request.user
    })

@login_required
def salir_sesion(request):
    logout(request)
    messages.success(request, 'Has cerrado sesión correctamente.')
    return redirect('alquiler:inicio_sesion')


@login_required
def vista_inicio(request):
    return render(request, 'inicio.html')


@staff_member_required
@permission_required('usuarios.view_rol', raise_exception=True)
def lista_roles(request):
    roles = Rol.objects.all().order_by('name')  # <-- usar name, no nombre_rol
    return render(request, 'lista_roles.html', {'roles': roles})


@login_required
@permission_required('usuarios.add_rol', raise_exception=True)
def crear_rol(request):
    if request.method == 'POST':
        form = RolForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Rol creado exitosamente')
            return redirect('alquiler:lista_roles')
        else:
            # Mostrar errores del formulario
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        form = RolForm()
    
    return render(request, 'crear_rol.html', {'form': form})
    

@login_required
@permission_required('usuarios.change_rol', raise_exception=True)
def editar_rol(request, rol_uuid):
    rol = get_object_or_404(Rol, uuid_id=rol_uuid)

    if request.method == 'POST':
        form = RolForm(request.POST, instance=rol)
        if form.is_valid():
            form.save()  # Ahora se guarda automáticamente todo
            messages.success(request, 'Rol actualizado exitosamente')
            return redirect('alquiler:lista_roles')
    else:
        form = RolForm(instance=rol)

    return render(request, 'editar_rol.html', {'form': form, 'rol': rol})

@login_required
@permission_required('usuarios.delete_rol', raise_exception=True)
def eliminar_rol(request, rol_uuid):
    rol = get_object_or_404(Rol, uuid_id=rol_uuid)
    other_roles = Rol.objects.exclude(uuid_id=rol.uuid_id)

    if request.method == 'POST':
        replacement_id = request.POST.get('replacement_role')

        try:
            with transaction.atomic():
                if rol.usuarios.exists():
                    if replacement_id:
                        replacement_role = get_object_or_404(Rol, uuid_id=replacement_id)
                        rol.usuarios.update(rol=replacement_role)
                    else:
                        # Si no seleccionaron nuevo rol, no se puede eliminar si hay usuarios
                        messages.error(request, 'Debes asignar un nuevo rol a los usuarios antes de eliminar este.')
                        return redirect('alquiler:eliminar_rol', rol_uuid=rol.uuid_id)

                rol.delete()
                messages.success(request, 'Rol eliminado exitosamente')
                return redirect('alquiler:lista_roles')
        except Exception as e:
            messages.error(request, f'Error al eliminar el rol: {e}')
    
    return render(request, 'eliminar_rol.html', {
        'rol': rol,
        'other_roles': other_roles
    })@login_required
@permission_required('usuarios.delete_rol', raise_exception=True)
def eliminar_rol(request, rol_uuid):
    rol = get_object_or_404(Rol, uuid_id=rol_uuid)
    other_roles = Rol.objects.exclude(uuid_id=rol.uuid_id)

    if request.method == 'POST':
        replacement_id = request.POST.get('replacement_role')

        try:
            with transaction.atomic():
                if rol.usuarios.exists():
                    if replacement_id:
                        replacement_role = get_object_or_404(Rol, uuid_id=replacement_id)
                        rol.usuarios.update(rol=replacement_role)
                    else:
                        # Si no seleccionaron nuevo rol, no se puede eliminar si hay usuarios
                        messages.error(request, 'Debes asignar un nuevo rol a los usuarios antes de eliminar este.')
                        return redirect('alquiler:eliminar_rol', rol_uuid=rol.uuid_id)

                rol.delete()
                messages.success(request, 'Rol eliminado exitosamente')
                return redirect('alquiler:lista_roles')
        except Exception as e:
            messages.error(request, f'Error al eliminar el rol: {e}')
    
    return render(request, 'eliminar_rol.html', {
        'rol': rol,
        'other_roles': other_roles
    })



@login_required
@permission_required('usuarios.change_usuario', raise_exception=True)
def asignar_rol(request, usuario_uuid):
    usuario = get_object_or_404(Usuario, uuid_id=usuario_uuid)
    roles = Rol.objects.all()
    
    if request.method == 'POST':
        rol_id = request.POST.get('rol')
        if rol_id:
            rol = get_object_or_404(Rol, id=rol_id)
            usuario.rol = rol
            usuario.save()
            
            # Los grupos se sincronizan automáticamente en el save()
            messages.success(request, f'Rol "{rol.name}" asignado correctamente a {usuario.nombre_usuario}')
            return redirect('alquiler:editar_usuario', usuario_uuid=usuario.uuid_id)
    return render(request, 'asignar_rol.html', {
        'usuario': usuario,
        'roles': roles
    })


@login_required
@permission_required('usuarios.view_usuario', raise_exception=True)
def lista_usuarios(request):
    query = request.GET.get('q', '')
    estado = request.GET.get('estado', '')
    rol_id = request.GET.get('rol', '')
    
    usuarios = Usuario.objects.all().order_by('nombre_usuario')
    
    if query:
        usuarios = usuarios.filter(nombre_usuario__icontains=query)
    
    if estado:
        usuarios = usuarios.filter(is_active=(estado == 'activo'))
    
    if rol_id:
        usuarios = usuarios.filter(rol_id=rol_id)
    
    paginator = Paginator(usuarios, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    roles = Rol.objects.all()
    
    return render(request, 'lista_usuarios.html', {
        'page_obj': page_obj,
        'roles': roles,
        'query': query,
        'estado_seleccionado': estado,
        'rol_seleccionado': int(rol_id) if rol_id else ''
    })


@login_required
@permission_required('usuarios.view_usuario', raise_exception=True)
def detalle_usuario(request, usuario_uuid):
    usuario = get_object_or_404(Usuario, uuid_id=usuario_uuid)

    return render(request, 'detalle_usuario.html', {'usuario': usuario})


@login_required
@permission_required('usuarios.change_usuario', raise_exception=True)
def editar_usuario(request, usuario_uuid):
    usuario = get_object_or_404(Usuario, uuid_id=usuario_uuid)

    
    if request.method == 'POST':
        form = UsuarioEditForm(request.POST, instance=usuario)
        if form.is_valid():
            usuario = form.save()
            
            # Actualizar grupo del usuario si cambió el rol
            if 'rol' in form.changed_data:
                usuario.groups.clear()
                if usuario.rol and usuario.rol.grupo:
                    usuario.groups.add(usuario.rol.grupo)
            
            messages.success(request, 'Usuario actualizado correctamente')
            
            # Si el usuario editado es el mismo que está logueado
            if usuario.id == request.user.id:
                update_session_auth_hash(request, usuario)
                messages.info(request, 'Tus datos de sesión han sido actualizados')
            
            return redirect('alquiler:detalle_usuario', usuario_uuid=usuario.uuid_id)

    else:
        form = UsuarioEditForm(instance=usuario)
    
    # Precargar datos de roles para el template
    roles_data = {
        rol.id: {
            'nombre': rol.nombre_rol,
            'descripcion': rol.descripcion,
            'permisos': [perm.name for perm in rol.permisos.all()]
        }
        for rol in Rol.objects.all().prefetch_related('permisos')
    }
    
    return render(request, 'editar_usuario.html', {
        'form': form,
        'usuario': usuario,
        'roles_data': roles_data
    })


@login_required
@permission_required('usuarios.change_usuario', raise_exception=True)
def cambiar_contrasena(request, usuario_uuid):
    usuario = get_object_or_404(Usuario, uuid_id=usuario_uuid)

    
    if request.method == 'POST':
        form = CambiarContrasenaForm(request.POST)
        if form.is_valid():
            usuario.password = make_password(form.cleaned_data['nueva_contrasena'])
            usuario.save()
            
            # Si el usuario editado es el mismo que está logueado
            if usuario.id == request.user.id:
                update_session_auth_hash(request, usuario)
                messages.info(request, 'Tu contraseña ha sido cambiada y tu sesión ha sido actualizada')
            else:
                messages.success(request, 'Contraseña cambiada correctamente')
            
            return redirect('alquiler:detalle_usuario', usuario_uuid=usuario.uuid_id)
    else:
        form = CambiarContrasenaForm()
    
    return render(request, 'cambiar_contrasena.html', {
        'form': form,
        'usuario': usuario
    })


@login_required
@permission_required('usuarios.change_usuario', raise_exception=True)
def cambiar_estado_usuario(request, usuario_uuid):
    usuario = get_object_or_404(Usuario, uuid_id=usuario_uuid)
    
    # No permitir desactivarse a sí mismo
    if usuario.uuid_id == request.user.uuid_id:
        messages.error(request, 'No puedes desactivar tu propia cuenta')
        return redirect('alquiler:lista_usuarios')
    
    usuario.is_active = not usuario.is_active
    usuario.save()
    
    action = "activado" if usuario.is_active else "desactivado"
    messages.success(request, f'Usuario {usuario.nombre_usuario} {action} correctamente')
    return redirect('alquiler:lista_usuarios')

@login_required
@permission_required('usuarios.delete_usuario', raise_exception=True)
def confirmar_eliminar_usuario(request, usuario_uuid):
    usuario = get_object_or_404(Usuario, uuid_id=usuario_uuid)

    
    # No permitir eliminarse a sí mismo
    if usuario.id == request.user.id:
        messages.error(request, 'No puedes eliminar tu propia cuenta')
        return redirect('alquiler:lista_usuarios')
    
    return render(request, 'confirmar_eliminar.html', {'usuario': usuario})


@login_required
@permission_required('usuarios.delete_usuario', raise_exception=True)
@require_POST
@csrf_protect
def eliminar_usuario(request, usuario_uuid):
    try:
        usuario = get_object_or_404(Usuario, uuid_id=usuario_uuid)

        
        # Validación: No puede eliminar su propia cuenta
        if usuario.id == request.user.id:
            messages.error(request, 'No puedes eliminar tu propia cuenta')
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False, 
                    'message': 'No puedes eliminar tu propia cuenta'
                })
            return redirect('alquiler:lista_usuarios')
        
        # Validación: No puede eliminar superusuarios (opcional)
        if hasattr(usuario, 'is_superuser') and usuario.is_superuser and not request.user.is_superuser:
            messages.error(request, 'No tienes permisos para eliminar este usuario')
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False, 
                    'message': 'No tienes permisos para eliminar este usuario'
                })
            return redirect('alquiler:lista_usuarios')
        
        # Guardar información antes de eliminar
        nombre_usuario = usuario.nombre_usuario
        usuario_email = getattr(usuario, 'email', 'N/A')
        
        # Registrar en auditoría ANTES de eliminar
        try:
            # Obtener IP del usuario
            ip_address = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
            if not ip_address:
                ip_address = request.META.get('REMOTE_ADDR', '127.0.0.1')
            
            # Crear log de auditoría
            UserAuditLog.objects.create(
                user=request.user,
                action='user_delete',
                ip_address=ip_address,
                status='success',
                target_user=usuario,
                details={
                    'deleted_user': nombre_usuario,
                    'deleted_email': usuario_email,
                    'deleted_by': request.user.nombre_usuario,
                    'timestamp': timezone.now().isoformat()
                }
            )
        except Exception as audit_error:
            logger.error(f"Error al registrar auditoría: {audit_error}")
        
        # Eliminar usuario
        usuario.delete()
        
        # Log del sistema
        logger.info(f"Usuario {nombre_usuario} eliminado por {request.user.nombre_usuario}")
        
        # Mensaje de éxito
        success_message = f'Usuario {nombre_usuario} eliminado correctamente'
        messages.success(request, success_message)
        
        # Respuesta para AJAX
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True, 
                'message': success_message,
                'redirect': '/usuarios/'  # Ajusta la URL según tu configuración
            })
        
        return redirect('alquiler:lista_usuarios')
        
    except Usuario.DoesNotExist:
        error_message = 'El usuario que intentas eliminar no existe'
        messages.error(request, error_message)
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False, 
                'message': error_message
            })
        
        return redirect('alquiler:lista_usuarios')
        
    except Exception as e:
        error_message = f'Error al eliminar el usuario: {str(e)}'
        logger.error(f"Error al eliminar usuario {usuario_uuid}: {str(e)}")
        messages.error(request, 'Ocurrió un error al eliminar el usuario')
        
        # Registrar error en auditoría
        try:
            ip_address = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
            if not ip_address:
                ip_address = request.META.get('REMOTE_ADDR', '127.0.0.1')
                
            UserAuditLog.objects.create(
                user=request.user,
                action='user_delete',
                ip_address=ip_address,
                status='failed',
                details={
                    'error': str(e),
                    'target_user_id': usuario_uuid,
                    'attempted_by': request.user.nombre_usuario
                }
            )
        except Exception as audit_error:
            logger.error(f"Error al registrar auditoría de fallo: {audit_error}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False, 
                'message': 'Ocurrió un error al eliminar el usuario'
            })
        
        return redirect('alquiler:lista_usuarios')

 

@login_required
@permission_required('usuarios.view_auditoria', raise_exception=True)
def auditoria_usuario(request, usuario_uuid):
    usuario = get_object_or_404(Usuario, uuid_id=usuario_uuid)

    query = request.GET.get('q', '')
    logs = UserAuditLog.objects.filter(user=usuario)

    if query:
        logs = logs.filter(
            Q(action__icontains=query) |
            Q(details__icontains=query) |
            Q(ip_address__icontains=query)
        )

    logs = logs.order_by('-timestamp')[:100]

    # ✅ Exportar CSV si se solicitó
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="auditoria_{usuario.nombre_usuario}.csv"'

        writer = csv.writer(response)
        writer.writerow(['Fecha/Hora', 'Acción', 'Estado', 'IP', 'Detalles'])

        for log in logs:
            writer.writerow([
                log.timestamp.strftime('%d/%m/%Y %H:%M'),
                log.get_action_display(),
                log.get_status_display(),
                log.ip_address,
                log.get_details_display()
            ])

        return response

    # 📊 Estadísticas de acceso últimos 6 meses
    six_months_ago = timezone.now() - timedelta(days=180)
    stats = UserAuditLog.objects.filter(
        user=usuario,
        timestamp__gte=six_months_ago
    ).annotate(
        month=TruncMonth('timestamp')
    ).values('month', 'status').annotate(
        count=Count('id')
    ).order_by('month')

    months = []
    success_data = []
    failed_data = []

    current_month = six_months_ago.replace(day=1)
    while current_month <= timezone.now():
        month_str = current_month.strftime('%b %Y')
        months.append(month_str)

        month_stats = [
            s for s in stats if s['month'] and
            s['month'].month == current_month.month and
            s['month'].year == current_month.year
        ]
        success = sum(s['count'] for s in month_stats if s['status'] == 'success')
        failed = sum(s['count'] for s in month_stats if s['status'] == 'failed')

        success_data.append(success)
        failed_data.append(failed)

        # Avanzar al siguiente mes
        if current_month.month == 12:
            current_month = current_month.replace(year=current_month.year + 1, month=1)
        else:
            current_month = current_month.replace(month=current_month.month + 1)

    stats_data = {
        'months': months,
        'success': success_data,
        'failed': failed_data
    }

    devices_raw = UserAuditLog.objects.filter(
        user=usuario,
        user_agent__isnull=False
    ).values('user_agent', 'ip_address').annotate(
        last_used=Max('timestamp'),
        count=Count('id')
    ).order_by('-last_used')[:5]

    devices = []
    for device in devices_raw:
        user_agent = device['user_agent']
        browser = 'Desconocido'
        os = 'Desconocido'
        is_mobile = False

        if 'Chrome' in user_agent:
            browser = 'Chrome'
        elif 'Firefox' in user_agent:
            browser = 'Firefox'
        elif 'Safari' in user_agent and 'Chrome' not in user_agent:
            browser = 'Safari'
        elif 'Edge' in user_agent:
            browser = 'Edge'

        if 'Windows' in user_agent:
            os = 'Windows'
        elif 'Mac' in user_agent:
            os = 'macOS'
        elif 'Linux' in user_agent:
            os = 'Linux'
        elif 'Android' in user_agent:
            os = 'Android'
            is_mobile = True
        elif 'iOS' in user_agent:
            os = 'iOS'
            is_mobile = True

        if 'Mobile' in user_agent or 'mobile' in user_agent:
            is_mobile = True

        devices.append({
            'browser': browser,
            'os': os,
            'is_mobile': is_mobile,
            'ip_address': device['ip_address'],
            'last_used': device['last_used'],
            'count': device['count'],
            'is_current': False
        })

    return render(request, 'auditoria_usuario.html', {
        'usuario': usuario,
        'logs': logs,
        'devices': devices,
        'stats_data': stats_data,
        'stats_data_json': json.dumps(stats_data),
        'query': query
    })