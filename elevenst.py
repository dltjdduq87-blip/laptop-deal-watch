"""11st ProductSearch adapter. Official guide: OpenApiGuide.tmall?commonGuideNo=1."""
import json
import os
import xml.etree.ElementTree as ET
from urllib import request, parse

ENDPOINT='https://openapi.11st.co.kr/openapi/OpenApiService.tmall'


def parse_search(raw):
    from catalog import base_record, notebook_name
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('ELEVENST_UNSAFE_XML')
    try:root=ET.fromstring(raw)
    except ET.ParseError:raise ValueError('ELEVENST_INVALID_XML') from None
    for node in root.iter():node.tag=node.tag.rsplit('}',1)[-1]
    if root.find('.//Error') is not None or root.find('.//ErrorCode') is not None:raise ValueError('ELEVENST_API_REJECTED')
    rows=[]
    for node in root.findall('.//Products/Product'):
        fields={k:node.findtext(k,'').strip() for k in ['ProductCode','ProductName','ProductPrice','Seller','DetailPageUrl','ProductDetailUrl','SalePrice']}
        name=fields['ProductName'];code=fields['ProductCode']
        if not notebook_name(name) or not code.isdigit() or not fields['ProductPrice'].isdigit():continue
        target=fields['ProductDetailUrl'] or fields['DetailPageUrl'];u=parse.urlsplit(target)
        if u.hostname not in ('www.11st.co.kr','11st.co.kr') or u.scheme not in ('http','https'):continue
        target=parse.urlunsplit(('https',u.netloc,u.path,u.query,''))
        price=int(fields['ProductPrice'])
        if price<=0:continue
        # Never preserve the API request echo, which may contain the key.
        record=base_record('11번가',ENDPOINT,json.dumps(fields,ensure_ascii=False),name=name,model=None,url=target,price=price,spec_text=name)
        record['product_id']=code;record['seller_name']=fields['Seller'];record['price_type']='11번가 공식 상품검색 API 공개가'
        record['api_sale_price_unverified']=int(fields['SalePrice']) if fields['SalePrice'].isdigit() else None
        record['html_sha256']=None
        rows.append(record)
    return rows


def collect():
    key=os.environ.get('ELEVENST_API_KEY','')
    if not key:raise ValueError('ELEVENST_API_KEY_MISSING')
    class NoRedirect(request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):raise ValueError('ELEVENST_REDIRECT_REJECTED')
    query=parse.urlencode({'key':key,'apiCode':'ProductSearch','keyword':'노트북 32GB','pageNum':1,'pageSize':100,'sortCd':'L','targetSearchPrd':'KOR'})
    req=request.Request(ENDPOINT+'?'+query,headers={'Accept':'application/xml','User-Agent':'LaptopDealWatch/1.0'})
    try:
        with request.build_opener(NoRedirect()).open(req,timeout=15) as r:
            raw=r.read(4000001)
        if len(raw)>4000000:raise ValueError('ELEVENST_RESPONSE_TOO_LARGE')
    except Exception:
        raise ValueError('ELEVENST_REQUEST_FAILED') from None
    return parse_search(raw)
