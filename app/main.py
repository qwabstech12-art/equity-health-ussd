from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from app.config.service import settings
from app.routes import ussd, handler

app = FastAPI(
        title="Equity Health Insurance USSD API",  
    description="", 
    version="1.0.0",
    contact={
        "name": "API Support",
        "url": "http://example.com/support",
        "email": "qwabsj@gmail.com"
    },
    docs_url="/doc/test", 
    redoc_url="/"

)




API_KEY = settings.api_key
API_KEY_NAME = "x-api-key"

# @app.middleware("http")
# async def api_key_middleware(request: Request, call_next):
#     open_routes = ["/", "/docs", "/open-endpoint", "/redoc"]
#     if request.url.path in open_routes:
#         return await call_next(request)

#     api_key = request.headers.get(API_KEY_NAME)
#     if api_key != API_KEY:
#         raise HTTPException(status_code=401, detail="Invalid or missing API key")

#     response = await call_next(request)
#     return response



app.include_router(ussd.router, prefix='/api', tags=['USSD'])
app.include_router(handler.router, prefix='/api/test', tags=['Handler'])