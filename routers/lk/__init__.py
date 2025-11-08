from fastapi import APIRouter

from routers.auth import get_password_hash
from routers.lk.call_analyze import router as call_analyze_router
from routers.lk.chart import router as chart_router
from routers.lk.chart_filter import router as chart_filter_router
from routers.lk.chart_parameter import router as chart_parameter_router
from routers.lk.column_display import router as column_display_router
from routers.lk.company import router as company_router
from routers.lk.integration import router as integration_router
from routers.lk.mode import router as mode_router
from routers.lk.mode_answer import router as mode_answer_router
from routers.lk.mode_question import router as mode_question_router
from routers.lk.mode_template import router as mode_template_router
from routers.lk.report import router as report_router
from routers.lk.static import router as static_router
from routers.lk.table_active_filter import router as table_active_filter_router
from routers.lk.table_view_settings import router as table_view_settings_router
from routers.lk.task import router as task_router
from routers.lk.transaction import router as transaction_router
from routers.lk.user import router as user_router


main_router = APIRouter()

main_router.include_router(user_router, tags=['users'])

main_router.include_router(report_router, tags=['report'])
main_router.include_router(integration_router, tags=['report'])

main_router.include_router(mode_router, tags=['mode'])
main_router.include_router(mode_answer_router, tags=['mode'])
main_router.include_router(mode_template_router, tags=['mode'])
main_router.include_router(mode_question_router, tags=['mode'])

main_router.include_router(task_router, tags=['task'])
main_router.include_router(call_analyze_router, tags=['task'])

main_router.include_router(chart_router, tags=['chart'])
main_router.include_router(chart_filter_router, tags=['chart'])
main_router.include_router(chart_parameter_router, tags=['chart'])

main_router.include_router(static_router)
main_router.include_router(table_active_filter_router)
main_router.include_router(table_view_settings_router)
main_router.include_router(transaction_router)
main_router.include_router(column_display_router)
main_router.include_router(company_router)
