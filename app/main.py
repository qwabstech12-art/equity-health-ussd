import secrets
from pathlib import Path

from fastapi import FastAPI, Request, Security
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import APIKeyHeader
from app.config.service import settings
from app.setup.connection import Base, engine
from app.setup.openapi_catalog import add_catalog
from app.routes import ussd, payments, admin, ebusua, payment_methods  # noqa: F401 -- import registers models on Base.metadata

Base.metadata.create_all(bind=engine)

app = FastAPI(
        title="Equity Health Insurance USSD API",
    description="",
    version="1.0.0",
    contact={
        "name": "API Support",
        "url": "https://glasontechnology.com/support",
        "email": "justice.dzomeku@glasontechnology.com"
    },
    docs_url="/doc/test",
    redoc_url="/"

)




API_KEY = settings.api_key
API_KEY_NAME = "x-api-key"

# Docs pages and the OpenAPI schema they load, plus the admin page shell (it holds no data;
# it asks for the key and sends it with every /api/admin request).
PUBLIC_PATHS = {"/", "/doc/test", "/doc/test/oauth2-redirect", "/openapi.json", "/admin", "/admin/logo.png"}

ADMIN_PREFIX = "/api/admin/"

# Payment gateway webhooks: Transflow/Uniwallet call these and can't send our key.
# POST only -- the GET audit lists on the same paths expose payment data and stay protected.
GATEWAY_WEBHOOKS = {
    "/api/ussd/payments/callbacks/mandate",
    "/api/ussd/payments/callbacks/uniwallet",
    "/api/ussd/payments/callbacks/mandate-transaction",
}


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    path = request.url.path
    if path == "/openapi.json":
        # Reload the catalog on every docs load so the Swagger examples match what's on sale now.
        try:
            await ussd.refresh_catalog()
        except Exception:
            pass  # the docs still load, just without catalog examples
        app.openapi_schema = None
    if path in PUBLIC_PATHS or (request.method == "POST" and path in GATEWAY_WEBHOOKS):
        return await call_next(request)

    # The admin data has its own key, so the integration key can't browse every customer's
    # records and the admin key can't call the USSD or payment endpoints.
    expected = API_KEY
    if path.startswith(ADMIN_PREFIX):
        expected = settings.admin_api_key
        if not expected:
            return JSONResponse(status_code=503, content={"detail": "Admin access is not configured"})

    # compare_digest: constant-time, so the key can't be guessed from response timing.
    # Returning (not raising) -- an HTTPException raised in middleware becomes a 500.
    provided = request.headers.get(API_KEY_NAME, "")
    if not secrets.compare_digest(provided.encode(), expected.encode()):
        return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})

    return await call_next(request)


# Enforcement is the middleware above; this only adds the "Authorize" button to the docs
# so the key can be entered once and sent with every "Try it out" request.
api_key_header = Security(APIKeyHeader(name=API_KEY_NAME, auto_error=False))

app.include_router(ussd.router, prefix='/api', tags=['USSD'], dependencies=[api_key_header])
app.include_router(ebusua.router, prefix='/api', tags=['Ebusua family plan'], dependencies=[api_key_header])
app.include_router(payments.router, prefix='/api', tags=['Payments'], dependencies=[api_key_header])
app.include_router(payment_methods.router, prefix='/api', tags=['Payment method'], dependencies=[api_key_header])
app.include_router(admin.router, prefix='/api', tags=['Admin'], dependencies=[api_key_header])



def openapi_with_catalog():
    if not app.openapi_schema:
        schema = get_openapi(
            title=app.title, version=app.version, description=app.description,
            contact=app.contact, routes=app.routes,
        )
        add_catalog(schema, ussd.POLICY_CONFIG)
        app.openapi_schema = schema
    return app.openapi_schema


app.openapi = openapi_with_catalog

STATIC = Path(__file__).parent / "static"


@app.get("/admin", include_in_schema=False)
async def admin_page():
    # no-cache: browsers re-check on every visit, so staff get a new version as soon as it's deployed.
    return FileResponse(STATIC / "admin.html", headers={"Cache-Control": "no-cache"})


@app.get("/admin/logo.png", include_in_schema=False)
async def admin_logo():
    return FileResponse(STATIC / "logo.png")
