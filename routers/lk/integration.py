import asyncio
import json
from typing import Optional, Annotated, List, Dict

import peewee
from beeline_portal.errors import BeelinePBXException
from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND, HTTP_503_SERVICE_UNAVAILABLE, HTTP_403_FORBIDDEN

from config import config as cfg
from data.models import User, Integration, IntegrationServiceName, Company
from integrations.amo_crm.amo_api_core import AmoApi
from integrations.beeline.process import BeelineProcessor
from integrations.bitrix.bitrix_api import Bitrix24
from integrations.mango.process import MangoProcessor
from integrations.sipuni.api import SipuniClient
from integrations.zoom.process import ZoomProcessor
from modules.exceptions import IntegrationConnectError, ObjectNotFoundError, IntegrationExistsError
from modules.json_processor.integration import IntegrationConstructor
from routers.auth import get_current_active_user
from schemas.integration import IntegrationPublicSchema, IntegrationCreateSchema, IntegrationUpdateSchema, \
    CRMUserPublicSchema, CRMFieldPublicSchema, PipelinePublicSchema
from schemas.user import UserModel

router = APIRouter()


def get_accessible_integration(
        current_user_id: int,
        integration_id: Optional[int] = None,
        allow_company_user: bool = True,
) -> peewee.ModelSelect:
    """
    Возвращает интеграции, к которым у пользователя есть доступ.
    """
    db_query = Integration.select()

    if integration_id is not None:
        db_query = db_query.where(Integration.id == integration_id)

    # Оставляем только интеграции тех компаний, которые доступны пользователю.
    if db_query.exists():
        user = User.get(id=current_user_id)
        companies = user.get_accessible_companies(allow_company_user=allow_company_user)
        db_query = db_query.where(Integration.company.in_(companies))

    return db_query


def get_public_integration(
        integration: Integration,
) -> IntegrationPublicSchema:

    i_data = integration.get_data()

    # Дешифруем поля для передачи на фронт в открытом виде.
    for field_name in IntegrationConstructor.sensitive_fields.get(integration.service_name, []):
        i_data['access'][field_name] = integration.get_decrypted_access_field(field_name)

    # Поля, которые не выводятся и не обновляются с фронта.
    if integration.service_name == IntegrationServiceName.AMOCRM:
        i_data['access'].pop('access_token', None)
        i_data['access'].pop('refresh_token', None)

    response = IntegrationPublicSchema(
        id=integration.id,
        service_name=integration.service_name,
        account_id=integration.account_id,
        data=json.dumps(i_data),
        company_id=integration.company.id,
    )
    return response


@router.get('/integrations/{integration_id}', response_model=IntegrationPublicSchema)
async def get_integration(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        integration_id: int,
):
    """
    Получить интеграцию по переданному ID.
    """
    integration = get_accessible_integration(current_user.id, integration_id=integration_id).first()
    if integration is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Интеграция не найдена.')

    response = get_public_integration(integration)
    return response


@router.get('/integrations', response_model=Dict)
async def get_integrations_list(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        service_name: Optional[IntegrationServiceName] = None,
        company_id: Optional[int] = Query(None),
        limit: int = Query(10, ge=1, le=100),
        offset: int = Query(0, ge=0),
):
    db_query = get_accessible_integration(current_user.id)

    # Фильтр по типу интеграции.
    if service_name:
        db_query = db_query.where(Integration.service_name == service_name)

    # Фильтр по компании.
    if company_id:
        company = Company.get_or_none(Company.id == company_id)
        if company is None:
            raise HTTPException(HTTP_404_NOT_FOUND, detail='Компания не найдена.')

        db_query = db_query.where(Integration.company == company)
        if not db_query.exists():
            raise HTTPException(HTTP_404_NOT_FOUND, detail='Компания не найдена.')

    total_count = db_query.count()
    integrations = db_query.limit(limit).offset(offset).order_by(Integration.id.asc())
    page_count = integrations.count()

    response = {
        'total_count': total_count,
        'count': page_count,
        'items': [get_public_integration(x) for x in integrations],
    }
    return response


@router.post('/integrations', response_model=IntegrationPublicSchema)
async def create_integration(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        integration_data: IntegrationCreateSchema,
):
    """
    Создание интеграции разрешено:
    - Системному администратору для любой компании.
    - Администратору компании для своей компании или для компаний, где он интегратор.
    - Пользователю компании в компаниях, где он интегратор.
    """
    user = User.get(id=current_user.id)
    accessible_companies = user.get_accessible_companies(company_id=integration_data.company_id)
    if not accessible_companies.exists():
        raise HTTPException(HTTP_403_FORBIDDEN, detail='В доступе отказано.')

    constructor = IntegrationConstructor(integration_data.telegram_id,
                                         integration_data.account_id,
                                         integration_data.data,
                                         integration_data.service_name,
                                         new_company_id=integration_data.company_id)
    try:
        integration = constructor.create()
    except ObjectNotFoundError as ex:
        raise HTTPException(HTTP_404_NOT_FOUND, detail=f'Не удалось создать интеграцию. {ex}')
    except (IntegrationConnectError, IntegrationExistsError) as ex:
        raise HTTPException(HTTP_503_SERVICE_UNAVAILABLE, detail=f'Не удалось создать интеграцию. {ex}')

    response = get_public_integration(integration)
    return response


@router.put('/integrations/{integration_id}', response_model=IntegrationPublicSchema)
async def update_integration(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        integration_id: int,
        integration_data: IntegrationUpdateSchema,
):
    """
    Обновление интеграции разрешено:
    - Системному администратору для любой компании.
    - Администратору компании для своей компании или для компаний, где он интегратор.
    - Пользователю компании в компаниях, где он интегратор.
    """
    user = User.get(id=current_user.id)
    accessible_companies = user.get_accessible_companies(company_id=integration_data.company_id)
    if not accessible_companies.exists():
        raise HTTPException(HTTP_403_FORBIDDEN, detail='В доступе отказано.')

    integration = get_accessible_integration(current_user.id, integration_id=integration_id).first()
    if integration is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Интеграция с таким ID не найдена.')

    constructor = IntegrationConstructor(integration_data.telegram_id,
                                         integration_data.account_id,
                                         integration_data.data,
                                         integration.service_name,
                                         new_company_id=integration_data.company_id)
    try:
        updated_integration = constructor.update(integration)
    except ObjectNotFoundError as ex:
        raise HTTPException(HTTP_404_NOT_FOUND, detail=f'Не удалось создать интеграцию. {ex}')
    except IntegrationConnectError as ex:
        raise HTTPException(HTTP_503_SERVICE_UNAVAILABLE, detail=f'Не удалось создать интеграцию. {ex}')

    response = get_public_integration(updated_integration)
    return response


@router.get('/integrations/{integration_id}/users', response_model=List[CRMUserPublicSchema])
async def get_users(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        integration_id: int,
):
    integration = get_accessible_integration(current_user.id, integration_id=integration_id).first()
    if integration is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Интеграция с таким ID не найдена.')

    if integration.service_name == IntegrationServiceName.AMOCRM:
        try:
            amo_api = AmoApi(integration)
        except KeyError:
            raise HTTPException(HTTP_400_BAD_REQUEST, detail='Не удалось подключиться к CRM. Проверьте интеграцию.')
        users = amo_api.get_users()
        response = []
        for user in users:
            response.append(CRMUserPublicSchema(id=str(user['id']), name=user['name']))

    elif integration.service_name == IntegrationServiceName.BITRIX24:
        webhook_url = integration.get_decrypted_access_field('webhook_url')
        bx24 = Bitrix24(webhook_url)

        users = await asyncio.to_thread(bx24.get_users)
        response = []
        for user in users:
            # Имя + Отчество + Фамилия. Пустые компоненты пропускаем.
            full_name = ' '.join(
                x for x in (
                    user.get('NAME'),
                    user.get('SECOND_NAME'),
                    user.get('LAST_NAME'))
                if x
            )
            response.append(CRMUserPublicSchema(id=user['ID'], name=full_name))

    elif integration.service_name == IntegrationServiceName.BEELINE:
        client = BeelineProcessor.get_api_client(integration)
        try:
            users = client.get_abonents()
        except BeelinePBXException:
            raise HTTPException(HTTP_400_BAD_REQUEST, detail='Не удалось подключиться к CRM. Проверьте интеграцию.')

        response = []
        for user in users:
            user_id = user.user_id
            if user.first_name:
                full_name = f'{user.first_name} {user.last_name}'
            else:
                full_name = user.last_name
            response.append(CRMUserPublicSchema(id=user_id, name=full_name))

    elif integration.service_name == IntegrationServiceName.SIPUNI:
        token = json.loads(integration.data).get('access').get('application_token')
        client = SipuniClient(integration.account_id, token)

        csv_users = client.get_managers()
        response = []
        for line in csv_users.splitlines()[1:]:
            fields = line.split(';')
            user_id = fields[0]
            user_name = fields[1].strip('" ')
            response.append(CRMUserPublicSchema(id=user_id, name=user_name))

    elif integration.service_name == IntegrationServiceName.MANGO:
        client = MangoProcessor.get_api_client(integration)
        try:
            users = client.get_users()
        except Exception:
            raise HTTPException(HTTP_400_BAD_REQUEST, detail='Не удалось подключиться к CRM. Проверьте интеграцию.')

        response = []
        for user in users:
            user_id = str(user['general']['user_id'])
            full_name = user['general']['name']
            response.append(CRMUserPublicSchema(id=user_id, name=full_name))

    elif integration.service_name == IntegrationServiceName.ZOOM:
        client = ZoomProcessor.get_api_client(integration)
        try:
            users = client.user.list().json()['users']
        except Exception:
            raise HTTPException(HTTP_400_BAD_REQUEST, detail='Не удалось подключиться к CRM. Проверьте интеграцию.')

        response = []
        for user in users:
            user_id = user['id']
            full_name = user['display_name']
            response.append(CRMUserPublicSchema(id=user_id, name=full_name))

    else:
        raise HTTPException(HTTP_400_BAD_REQUEST, detail='Неизвестный тип интеграции.')

    return response


@router.get('/integrations/{integration_id}/fields/{entity_type}', response_model=List[CRMFieldPublicSchema])
async def get_integration_fields(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        integration_id: int,
        entity_type: str,
):
    """
    Возвращает все поля CRM/телефонии для указанного типа сущности.
    """
    integration = get_accessible_integration(current_user.id, integration_id=integration_id).first()
    if integration is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Интеграция с таким ID не найдена.')

    if integration.service_name == IntegrationServiceName.AMOCRM:
        try:
            amo_api = AmoApi(integration)
        except KeyError:
            raise HTTPException(HTTP_400_BAD_REQUEST, detail='Не удалось подключиться к CRM. Проверьте интеграцию.')
        try:
            fields = amo_api.get_custom_fields(entity_type)
        except TypeError:
            raise HTTPException(HTTP_400_BAD_REQUEST, detail='Не удалось получить список полей. Проверьте интеграцию.')
        response = [
            CRMFieldPublicSchema(
                id=str(x['id']),
                name=x['name'],
                options=x['enums'],
            ) for x in fields
        ]

    elif integration.service_name == IntegrationServiceName.BITRIX24:
        webhook_url = integration.get_decrypted_access_field('webhook_url')
        bx24 = Bitrix24(webhook_url)

        if entity_type == 'deal':
            fields = await asyncio.to_thread(bx24.get_deal_fields)
        elif entity_type == 'lead':
            fields = await asyncio.to_thread(bx24.get_lead_fields)
        elif entity_type == 'contact':
            fields = await asyncio.to_thread(bx24.get_contact_fields)
        elif entity_type == 'company':
            fields = await asyncio.to_thread(bx24.get_company_fields)
        else:
            raise HTTPException(HTTP_400_BAD_REQUEST, detail=f'Неизвестный тип сущности: {entity_type}.')

        response = []
        for field_id, field_data in fields.items():
            # formLabel для кастомных полей, title для системных полей.
            name = field_data.get('formLabel') or field_data['title']
            response.append(CRMFieldPublicSchema(
                id=field_id,
                name=name,
                options=field_data.get('items'),
            ))

    else:
        raise HTTPException(HTTP_400_BAD_REQUEST, detail='Неизвестный тип интеграции.')

    return response


@router.get('/integrations/{integration_id}/pipelines_and_statuses', response_model=List[PipelinePublicSchema])
async def get_integration_pipelines(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        integration_id: int,
):
    integration = get_accessible_integration(current_user.id, integration_id=integration_id).first()
    if integration is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Интеграция не найдена.')

    if integration.service_name == IntegrationServiceName.AMOCRM:
        try:
            amo_api = AmoApi(integration)
        except KeyError:
            raise HTTPException(HTTP_400_BAD_REQUEST, detail='Не удалось подключиться к CRM. Проверьте интеграцию.')
        pipelines = amo_api.get_pipelines()
        response = [
            PipelinePublicSchema(
                id=x['id'],
                name=x['name'],
                statuses=x['statuses'],
            ) for x in pipelines
        ]

    elif integration.service_name == IntegrationServiceName.BITRIX24:
        webhook_url = integration.get_decrypted_access_field('webhook_url')
        bx24 = Bitrix24(webhook_url)
        pipelines = await asyncio.to_thread(bx24.get_funnels_with_stages)
        response = [
            PipelinePublicSchema(
                id=x['id'],
                name=x['name'],
                statuses=x['stages'],
            ) for x in pipelines
        ]

        # Этапы лидов.
        lead_stages = await asyncio.to_thread(bx24.get_status_list, 'STATUS')
        response.append(
            PipelinePublicSchema(
                id=int(cfg.BITRIX24_LEAD_PIPELINE_ID),
                name='ЛИДЫ',
                statuses=lead_stages,
            )
        )

    else:
        raise HTTPException(HTTP_400_BAD_REQUEST, detail='Неизвестный тип интеграции.')

    return response
