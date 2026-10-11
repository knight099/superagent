"""Bound HTTP input before JSON parsing or model/database work."""
from starlette.responses import JSONResponse


class BodyLimit:
    def __init__(self,app,max_bytes=65536):
        self.app=app
        self.max_bytes=max_bytes

    async def __call__(self,scope,receive,send):
        if scope['type']!='http':
            await self.app(scope,receive,send)
            return
        headers=dict(scope.get('headers',[]))
        length=headers.get(b'content-length')
        try:
            oversized=length is not None and int(length)>self.max_bytes
        except ValueError:
            await JSONResponse({'detail':'Invalid content length'},status_code=400)(scope,receive,send)
            return
        chunks=[]
        total=0
        while not oversized:
            message=await receive()
            if message['type']=='http.disconnect':
                return
            body=message.get('body',b'')
            total+=len(body)
            if total>self.max_bytes:
                oversized=True
                break
            chunks.append(body)
            if not message.get('more_body',False):
                break
        if oversized:
            await JSONResponse({'detail':'Request body exceeds 64 KiB limit'},status_code=413)(scope,receive,send)
            return
        supplied=False
        async def bounded_receive():
            nonlocal supplied
            if not supplied:
                supplied=True
                return {'type':'http.request','body':b''.join(chunks),'more_body':False}
            return await receive()
        await self.app(scope,bounded_receive,send)
