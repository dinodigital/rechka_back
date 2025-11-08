from typing import Dict, Annotated, Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from starlette.status import HTTP_404_NOT_FOUND

from data.models import Company, Transaction, main_db
from routers.auth import get_current_active_user
from schemas.transaction import TransactionPublicSchema, TransactionCreateSchema
from schemas.user import UserModel


router = APIRouter()


@router.get('/transactions/{transaction_id}', response_model=TransactionPublicSchema)
async def get_transaction(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        transaction_id: int,
):
    """
    Доступ к транзакции есть у:
    1. Системного администратора.
    2. У администратора компании, связанной с транзакцией.
    """
    transaction = Transaction.get_or_none(Transaction.id == transaction_id)
    if transaction is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Транзакция не найдена.')

    if (
            not current_user.is_admin
            and
            not (current_user.company_id == transaction.company_id and current_user.company_role == Company.Roles.ADMIN)
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Транзакция не найдена.')

    return transaction


@router.get('/transactions', response_model=Dict)
async def get_transactions_list(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        company_id: Optional[int] = None,
        limit: int = Query(10, ge=1, le=100),
        offset: int = Query(0, ge=0),
):
    """
    Системный администратор имеет доступ ко всем транзакциям.
    Администратор компании имеет доступ к транзакциям своей компании.
    """
    db_query = Transaction.select()

    # Фильтр по компании.
    if company_id is not None:
        if (
                not current_user.is_admin
                and
                not (current_user.company_id == company_id and current_user.company_role == Company.Roles.ADMIN)
        ):
            raise HTTPException(HTTP_404_NOT_FOUND, detail='Компания не найдена.')
        company = Company.get_or_none(Company.id == company_id)
        if company is None:
            raise HTTPException(HTTP_404_NOT_FOUND, detail='Компания не найдена.')

        db_query = db_query.where(Transaction.company == company)

    total_count = db_query.count()
    transactions = db_query.limit(limit).offset(offset).order_by(Transaction.id.asc())
    page_count = transactions.count()

    response = {
        'total_count': total_count,
        'count': page_count,
        'items': [TransactionPublicSchema.model_validate(x) for x in transactions],
    }
    return response


@router.post('/transactions', response_model=TransactionPublicSchema)
async def create_transaction(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        data: TransactionCreateSchema,
):
    company = Company.get_or_none(id=data.company_id)

    if company is None or (
            not current_user.is_admin
            and
            not (current_user.company_id == data.company_id and current_user.company_role == Company.Roles.ADMIN)
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Компания не найдена.')

    transaction = company.add_balance(data.minutes * 60,
                                      payment_sum=data.payment_sum,
                                      payment_currency=data.payment_currency,
                                      payment_type=data.payment_type,
                                      description=data.description)

    return transaction
