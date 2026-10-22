from django.http import Http404
from rest_framework.exceptions import PermissionDenied

from apps.audit import services as audit

from .models import Company, Membership


class IsolationError(Http404):
    """Empresa inexistente OU sem vínculo: ambas viram 404 para não revelar existência."""


def resolve_company(request, company_id, *, lock=False):
    """Única porta de entrada para dados de uma empresa.

    O id vem da URL e nunca é confiado: só é aceito com vínculo ativo do usuário (e empresa ativa).
    Administrador da plataforma pode alcançar a empresa, mas sem papel (request.membership = None),
    e cada acesso é auditado. Os endpoints decidem o que isso permite.
    """
    request.membership = None
    companies = Company.objects.select_for_update(no_key=True) if lock else Company.objects
    company = companies.filter(pk=company_id).first()
    if company is None:
        raise IsolationError()
    if request.user.is_platform_admin:
        audit.record(request, "platform.company_access", company=company, path=request.path)
        return company
    membership = Membership.objects.filter(user=request.user, company=company, is_active=True).first()
    if membership is not None and company.is_active:
        request.membership = membership
        return company
    raise IsolationError()


def require_role(request, *roles):
    """Exige vínculo com um dos papéis. Contas da plataforma não recebem papel operacional."""
    membership = getattr(request, "membership", None)
    if membership is None or membership.role not in roles:
        raise PermissionDenied("Você não tem permissão para esta operação.")
    return membership
