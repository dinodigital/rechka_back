from typing import Optional, Annotated, Dict

from fastapi import APIRouter, Depends, Query, HTTPException
from peewee import Case, fn
from starlette.status import HTTP_404_NOT_FOUND

from data.models import Transaction
from data.models import User, Company
from routers.auth import get_current_active_user
from routers.helpers import update_endpoint_object
from schemas.company import CompanyPublicSchema, CompanyPartialUpdateSchema, CompanyExtendedPublicSchema
from schemas.user import UserModel


router = APIRouter()


@router.get('/companies/{company_id}', response_model=CompanyPublicSchema)
async def get_company(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        company_id: int,
):
    company = Company.get_or_none(id=company_id)
    if company is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Компания не найдена.')
    return company



@router.get('/companies', response_model=Dict)
async def get_companies(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        company_name: Optional[str] = None,
        search_query: Optional[str] = None,
        has_payments: Optional[bool] = None,
        limit: int = Query(10, ge=1, le=500),
        offset: int = Query(0, ge=0),
):
    """
    company_name: поиск по полю Company.name.
    search_query: поиск по полям Company.name, Company.firm_name.

    company_name и search_query являются взаимоисключающими аргументами.
    """

    user = User.get(id=current_user.id)

    # Компании, к которым разрешен доступ пользователю.
    db_query = user.get_accessible_companies(allow_company_user=True)

    if company_name:
        db_query = db_query.where(
            Company.name.contains(company_name)
        )
    elif search_query:
        db_query = db_query.where(
            Company.name.contains(search_query) |
            Company.firm_name.contains(search_query)
        )

    # Поиск компаний, имеющих платежи.
    if has_payments is not None:
        transactions = (
            Transaction
            .select(Company.id)
            .join(Company)
            .where(
                Transaction.payment_sum.is_null(False),
                Transaction.payment_sum > 0,
            )
            .distinct()
        )
        companies_with_payments = {x.company.id for x in transactions}
        db_query = db_query.where(Company.id.in_(companies_with_payments))

    # Сортируем ответ так, чтобы компания текущего пользователя была на первом месте.
    db_query = db_query.order_by(
        Case(None, ((Company.id == current_user.company_id, 0),), default=1),
        Company.name,
    )

    total_count = db_query.count()
    companies = db_query.limit(limit).offset(offset)
    page_count = companies.count()

    # Суперпользователь также получает количество пользователей в каждой из компаний.
    if current_user.is_admin:
        user_counts = (
            User
            .select(User.company, fn.COUNT(User.id).alias('users_count'))
            .group_by(User.company)
            .where(User.company.in_(companies))
        )
        user_counts_dict = {x.company.id: x.users_count for x in user_counts}
    else:
        user_counts_dict = {}

    companies_validated = []
    for company in companies:
        company_kwargs = dict(
            id=company.id,
            name=company.name,
            firm_name=company.firm_name,
            seconds_balance=company.seconds_balance,
        )
        if current_user.is_admin:
            company_kwargs.update({
                'bitrix_company_id': company.bitrix_company_id,
                'users_count': user_counts_dict.get(company.id, 0),
            })
            schema = CompanyExtendedPublicSchema
        else:
            schema = CompanyPublicSchema
        companies_validated.append(schema(**company_kwargs))

    response = {
        'total_count': total_count,
        'count': page_count,
        'items': companies_validated,
    }
    return response


@router.patch('/companies/{company_id}', response_model=CompanyPublicSchema)
async def partial_update_company(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        company_id: int,
        data: CompanyPartialUpdateSchema,
):
    if not current_user.is_admin:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Компания не найдена.')

    company = Company.get_or_none(id=company_id)
    if company is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Компания не найдена.')

    company = update_endpoint_object(company, data, False)
    return company
