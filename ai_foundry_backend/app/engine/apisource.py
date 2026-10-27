"""Reads the user's real API description (Postman collection v2.x or OpenAPI/Swagger) into a flat list of endpoints.

Test cases are written against these endpoints, never against names invented from table names. The database schema is
used afterwards to understand each endpoint's fields (types, lengths, required, unique, enums)."""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import yaml

METHODS = ["get", "post", "put", "patch", "delete"]
SECRET_HEADERS = {"authorization", "x-api-key", "api-key", "cookie", "x-auth-token", "proxy-authorization"}
VERSION = re.compile(r"^(api|v\d+(\.\d+)?|rest|public)$", re.I)


@dataclass
class Endpoint:
    method: str
    path: str  # "/api/v1/tasks/{id}" - path parameters always written as {name}
    name: str = ""
    folder: str = ""
    body: Optional[dict[str, Any]] = None
    headers: dict[str, str] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)  # from an OpenAPI contract
    ok_status: str = "2xx"  # exact code when the source documents one
    table: Optional[str] = None  # filled in by match_tables

    @property
    def key(self) -> str:
        return f"{self.method} {self.path}"

    def has_path_param(self) -> bool:
        return "{" in self.path

    def resource(self) -> str:
        return re.sub(r"/\{[^/]+\}$", "", self.path)


@dataclass
class ApiSource:
    kind: str  # postman | openapi
    title: str
    base_url: str
    endpoints: list[Endpoint]


def _mask(headers: dict[str, str]) -> dict[str, str]:
    """Credentials in the user's collection are replaced by a variable so they are never stored or exported."""
    return {k: ("{{authToken}}" if k.lower() in SECRET_HEADERS else v) for k, v in headers.items()}


def _path_params(p: str) -> str:
    p = re.sub(r"/:([A-Za-z_][\w-]*)", r"/{\1}", p)  # Postman :id
    return re.sub(r"\{\{([^}]+)\}\}", r"{\1}", p)  # Postman {{id}} -> {id}


# ---- Postman ---------------------------------------------------------------------------------
def _postman_url(u: Any) -> tuple[str, str]:
    raw = u if isinstance(u, str) else (u or {}).get("raw", "")
    raw = raw.split("?")[0]
    m = re.match(r"^(https?://[^/]+|\{\{[^}]+\}\})(/.*)?$", raw)
    if m:
        return m.group(1), m.group(2) or "/"
    if isinstance(u, dict) and u.get("path"):
        return "", "/" + "/".join(str(x) for x in u["path"])
    return "", raw if raw.startswith("/") else "/" + raw


def _postman_body(req: dict[str, Any]) -> Optional[dict[str, Any]]:
    b = req.get("body") or {}
    mode = b.get("mode")
    if mode == "raw":
        try:
            v = json.loads(b.get("raw") or "")
            return v if isinstance(v, dict) else None
        except ValueError:
            return None
    if mode in {"urlencoded", "formdata"}:
        return {p["key"]: p.get("value", "") for p in b.get(mode, []) if p.get("key") and not p.get("disabled")}
    return None


def _walk_postman(items: list[Any], folder: str, out: list[Endpoint], bases: list[str]) -> None:
    for it in items:
        if "item" in it:
            _walk_postman(it["item"], f"{folder}/{it.get('name', '')}".strip("/"), out, bases)
            continue
        req = it.get("request")
        if not isinstance(req, dict):
            continue
        base, path = _postman_url(req.get("url"))
        if base:
            bases.append(base)
        ok = "2xx"
        for r in it.get("response") or []:
            if isinstance(r.get("code"), int) and 200 <= r["code"] < 300:
                ok = str(r["code"])
                break
        out.append(
            Endpoint(
                method=str(req.get("method", "GET")).upper(), path=_path_params(path), name=str(it.get("name", "")), folder=folder, body=_postman_body(req),
                headers=_mask({h["key"]: str(h.get("value", "")) for h in req.get("header") or [] if h.get("key") and not h.get("disabled") and h["key"].lower() not in {"content-length", "host"}}),
                ok_status=ok,
            )
        )


# ---- OpenAPI ---------------------------------------------------------------------------------
def _resolve(doc: dict[str, Any], node: Any, depth: int = 0) -> Any:
    if depth > 12 or not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/"):
        cur: Any = doc
        for part in ref[2:].split("/"):
            cur = cur.get(part.replace("~1", "/").replace("~0", "~")) if isinstance(cur, dict) else None
        return _resolve(doc, cur, depth + 1)
    return node


def _example(doc: dict[str, Any], schema: Any, depth: int = 0) -> Any:
    s = _resolve(doc, schema)
    if not isinstance(s, dict) or depth > 6:
        return None
    if "example" in s:
        return s["example"]
    if "default" in s:
        return s["default"]
    if s.get("enum"):
        return s["enum"][0]
    for k in ("allOf",):
        if s.get(k):
            merged: dict[str, Any] = {}
            for part in s[k]:
                v = _example(doc, part, depth + 1)
                if isinstance(v, dict):
                    merged.update(v)
            return merged
    for k in ("oneOf", "anyOf"):
        if s.get(k):
            return _example(doc, s[k][0], depth + 1)
    t, f = s.get("type"), s.get("format", "")
    if t == "object" or "properties" in s:
        return {k: _example(doc, v, depth + 1) for k, v in (s.get("properties") or {}).items() if not (_resolve(doc, v) or {}).get("readOnly")}
    if t == "array":
        return [_example(doc, s.get("items"), depth + 1)]
    if t == "integer":
        return int(s.get("minimum", 1))
    if t == "number":
        return float(s.get("minimum", 1.5))
    if t == "boolean":
        return True
    if f == "date-time":
        return "2025-01-15T10:30:00Z"
    if f == "date":
        return "2025-01-15"
    if f == "uuid":
        return "3fa85f64-5717-4562-b3fc-2c963f66afa6"
    if f == "email":
        return "user@example.com"
    n = s.get("maxLength")
    return "sample"[:n] if n else "sample"


def _openapi(doc: dict[str, Any]) -> ApiSource:
    servers = doc.get("servers") or []
    base = servers[0].get("url", "") if servers else (f"{(doc.get('schemes') or ['https'])[0]}://{doc['host']}{doc.get('basePath', '')}" if doc.get("host") else "")
    eps: list[Endpoint] = []
    for p, item in (doc.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for m in METHODS:
            op = item.get(m)
            if not isinstance(op, dict):
                continue
            body: Optional[dict[str, Any]] = None
            req_fields: list[str] = []
            schema = None
            rb = _resolve(doc, op.get("requestBody")) or {}
            content = (rb.get("content") or {}) if isinstance(rb, dict) else {}
            media = content.get("application/json") or next(iter(content.values()), None)
            if media:
                schema = media.get("schema")
            for prm in (op.get("parameters") or []) + (item.get("parameters") or []):  # Swagger 2 body parameter
                prm = _resolve(doc, prm)
                if isinstance(prm, dict) and prm.get("in") == "body":
                    schema = prm.get("schema")
            if schema is not None:
                rs = _resolve(doc, schema)
                ex = _example(doc, schema)
                body = ex if isinstance(ex, dict) else None
                if isinstance(rs, dict):
                    req_fields = [str(x) for x in rs.get("required", [])]
            ok = next((c for c in (op.get("responses") or {}) if str(c).startswith("2") and str(c).isdigit()), "2xx")
            headers = {"Content-Type": "application/json"} if body is not None else {}
            if op.get("security") or doc.get("security"):
                headers["Authorization"] = "{{authToken}}"
            eps.append(Endpoint(method=m.upper(), path=p, name=str(op.get("summary") or op.get("operationId") or ""), folder=(op.get("tags") or [""])[0], body=body, headers=headers, required=req_fields, ok_status=str(ok)))
    return ApiSource("openapi", (doc.get("info") or {}).get("title", "API"), base, eps)


# ---- entry point -----------------------------------------------------------------------------
def parse_api_source(text: str) -> ApiSource:
    try:
        doc = json.loads(text) if text.strip().startswith("{") else yaml.safe_load(text)
    except (ValueError, yaml.YAMLError) as e:
        raise ValueError(f"The file is not valid JSON or YAML: {str(e)[:120]}")
    if not isinstance(doc, dict):
        raise ValueError("Unrecognised file. Provide a Postman collection (v2.x) or an OpenAPI / Swagger document.")
    if isinstance(doc.get("item"), list):
        eps: list[Endpoint] = []
        bases: list[str] = []
        _walk_postman(doc["item"], "", eps, bases)
        if not eps:
            raise ValueError("The Postman collection contains no requests.")
        base = max(set(bases), key=bases.count) if bases else ""
        return ApiSource("postman", (doc.get("info") or {}).get("name", "Collection"), base, eps)
    if "paths" in doc:
        src = _openapi(doc)
        if not src.endpoints:
            raise ValueError("The OpenAPI document has no operations.")
        return src
    raise ValueError("Unrecognised file. Provide a Postman collection (v2.x) or an OpenAPI / Swagger document.")


# ---- matching endpoints to tables ------------------------------------------------------------
def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def singular(w: str) -> str:
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    return w[:-1] if w.endswith("s") and not w.endswith("ss") and len(w) > 3 else w


def key_to_column(table: Any, key: str) -> Optional[Any]:
    """Map a request field (camelCase, snake_case, fooId ...) to the column it stores into."""
    k = norm(key)
    for c in table.columns:
        if norm(c.name) == k:
            return c
    return None


def match_tables(source: ApiSource, schema: Any) -> None:
    for ep in source.endpoints:
        segs = [norm(singular(s.lower())) for s in ep.path.split("/") if s and "{" not in s and not VERSION.match(s)]
        keys = list((ep.body or {}).keys())
        best, best_score = None, 0.0
        for t in schema.tables:
            tn = norm(t.name)
            score = 0.0
            if segs:
                last = segs[-1]
                if tn == last or tn == last + "s" or tn.endswith(last) or (len(last) > 3 and last in tn):
                    score += 2.0 if tn.endswith(last) else 1.0
                elif any(len(s) > 3 and tn.endswith(s) for s in segs[:-1]):
                    score += 0.5
            if keys:
                hit = sum(1 for k in keys if key_to_column(t, k))
                if hit >= 2 or (hit and len(keys) == 1):
                    score += 2.0 * hit / len(keys)
            if score > best_score:
                best, best_score = t.name, score
        ep.table = best if best_score >= 1.0 else None


def deep(v: Any) -> Any:
    return copy.deepcopy(v)
