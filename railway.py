"""دیپلوی خودکار سلف روی اکانت Railway خود کاربر (نه روی اکانت ادمین).

مدل: کاربر توکن Railway خودش رو می‌ده (railway.com/account/tokens ← Account Token)
و بات با همون توکن روی اکانت خودش پروژه می‌سازه:
  projectCreate → serviceCreate از ریپوی mamad3743/self → ست متغیرها →
  volume /data → دامنه → دیپلوی.

توکن فقط برای فراخوانی API با اکانت خود کاربر استفاده می‌شه و روی سرور ما
فقط اگه خود کاربر بخواد برای چک وضعیت/ریدیپلوی ذخیره می‌شه (قابل حذف با /forget).
"""
import os
import asyncio

import aiohttp

ENDPOINT = "https://backboard.railway.com/graphql/v2"
DEFAULT_REPO = os.getenv("SELF_REPO", "mamad3743/self")
DEFAULT_BRANCH = os.getenv("SELF_BRANCH", "main") or "main"


class RailwayError(Exception):
    pass


async def gql(token: str, query: str, variables: dict | None = None, timeout: int = 30) -> dict:
    headers = {"Authorization": f"Bearer {token.strip()}", "Content-Type": "application/json"}
    payload = {"query": query, "variables": variables or {}}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as s:
            async with s.post(ENDPOINT, json=payload, headers=headers) as r:
                try:
                    data = await r.json(content_type=None)
                except Exception:
                    text = (await r.read()).decode("utf-8", "ignore")[:300]
                    raise RailwayError(f"پاسخ نامعتبر از Railway (HTTP {r.status}): {text}")
    except RailwayError:
        raise
    except Exception as e:  # noqa
        raise RailwayError(f"اتصال به Railway برقرار نشد: {type(e).__name__}")
    errs = data.get("errors")
    if errs:
        msg = "; ".join(str(e.get("message", "?")) for e in errs)[:600]
        low = msg.lower()
        if "not authorized" in low or "unauthorized" in low or "invalid token" in low:
            raise RailwayError("توکن معتبر نیست (Not Authorized). از railway.com/account/tokens یه Account Token جدید بساز.")
        raise RailwayError(msg)
    return data.get("data") or {}


async def validate_token(token: str) -> dict:
    """توکن رو چک می‌کنه؛ خروجی: {id, name, email}."""
    data = await gql(token, "query { me { id name email } }")
    me = data.get("me")
    if not me or not me.get("id"):
        raise RailwayError("توکن معتبر نیست.")
    return me


async def create_project(token: str, name: str) -> str:
    data = await gql(
        token,
        "mutation projectCreate($input: ProjectCreateInput!) { projectCreate(input: $input) { id } }",
        {"input": {"name": name}},
    )
    pid = (data.get("projectCreate") or {}).get("id")
    if not pid:
        raise RailwayError("ساخت پروژه انجام نشد.")
    return pid


async def get_production_env(token: str, project_id: str) -> str:
    data = await gql(
        token,
        "query project($id: String!) { project(id: $id) { environments { edges { node { id name } } } } }",
        {"id": project_id},
    )
    edges = (((data.get("project") or {}).get("environments") or {}).get("edges")) or []
    for e in edges:
        node = e.get("node") or {}
        if (node.get("name") or "").lower() == "production" and node.get("id"):
            return node["id"]
    if edges and edges[0].get("node", {}).get("id"):
        return edges[0]["node"]["id"]
    raise RailwayError("محیط production پیدا نشد.")


async def create_service(token: str, project_id: str, repo: str, branch: str | None = None) -> str:
    src = {"repo": repo}
    variables: dict = {"projectId": project_id, "name": "self", "source": src}
    if branch:
        variables["branch"] = branch
    try:
        data = await gql(
            token,
            "mutation serviceCreate($input: ServiceCreateInput!) { serviceCreate(input: $input) { id name } }",
            {"input": variables},
        )
    except RailwayError as e:
        msg = str(e)
        if "github" in msg.lower() or "repo" in msg.lower() or "not found" in msg.lower():
            raise RailwayError(
                "اتصال به گیت‌هاب انجام نشد. توی داشبورد Railway اکانت گیت‌هابت رو وصل کن "
                "(یا ریپو رو Fork کن) و دوباره امتحان کن. جزئیات: " + msg[:200]
            )
        raise
    sid = (data.get("serviceCreate") or {}).get("id")
    if not sid:
        raise RailwayError("ساخت سرویس انجام نشد.")
    return sid


async def set_variables(token: str, project_id: str, env_id: str, service_id: str, variables: dict):
    if not variables:
        return
    await gql(
        token,
        "mutation variableCollectionUpsert($input: VariableCollectionUpsertInput!) { variableCollectionUpsert(input: $input) }",
        {"input": {"projectId": project_id, "environmentId": env_id, "serviceId": service_id,
                   "variables": {k: str(v) for k, v in variables.items()}}},
    )


async def create_volume(token: str, project_id: str, service_id: str, env_id: str, mount: str = "/data") -> str | None:
    try:
        data = await gql(
            token,
            "mutation volumeCreate($input: VolumeCreateInput!) { volumeCreate(input: $input) { id } }",
            {"input": {"projectId": project_id, "serviceId": service_id, "mountPath": mount, "environmentId": env_id}},
        )
        return ((data.get("volumeCreate") or {}).get("id"))
    except RailwayError as e:
        # اگه Volume از قبل هست یا پلن اجازه نمی‌ده، دیپلوی رو متوقف نکن
        if "already" in str(e).lower() or "exists" in str(e).lower():
            return None
        raise RailwayError("ساخت Volume (/data) نشد: " + str(e)[:250])


async def create_domain(token: str, service_id: str, env_id: str) -> str | None:
    try:
        data = await gql(
            token,
            "mutation serviceDomainCreate($input: ServiceDomainCreateInput!) { serviceDomainCreate(input: $input) { domain } }",
            {"input": {"serviceId": service_id, "environmentId": env_id}},
        )
        return ((data.get("serviceDomainCreate") or {}).get("domain"))
    except RailwayError:
        return None  # کاربر خودش از داشبورد Generate Domain می‌زنه


async def trigger_deploy(token: str, service_id: str, env_id: str):
    await gql(
        token,
        "mutation serviceInstanceDeployV2($serviceId: String!, $environmentId: String!) { serviceInstanceDeployV2(serviceId: $serviceId, environmentId: $environmentId) }",
        {"serviceId": service_id, "environmentId": env_id},
    )


async def deployment_status(token: str, project_id: str, service_id: str, limit: int = 3) -> list:
    data = await gql(
        token,
        "query deployments($input: DeploymentListInput!) { deployments(input: $input, first: 5) { edges { node { id status createdAt } } } }",
        {"input": {"projectId": project_id, "serviceId": service_id}},
    )
    edges = ((data.get("deployments") or {}).get("edges")) or []
    return [e.get("node") or {} for e in edges[:limit]]


def build_variables(panel_password: str, api_id: str = "", api_hash: str = "", timezone: str = "Asia/Tehran") -> dict:
    """متغیرهایی که باید روی سرویس ست بشن (همون چیزایی که قبلاً دستی توی Railway می‌زدی)."""
    panel_password = (panel_password or "").strip()
    if len(panel_password) < 6:
        raise ValueError("رمز پنل حداقل ۶ کاراکتر باشه")
    out = {"PANEL_PASSWORD": panel_password, "TIMEZONE": (timezone or "Asia/Tehran").strip() or "Asia/Tehran"}
    if api_id.strip() and api_hash.strip():
        out["API_ID"] = api_id.strip()
        out["API_HASH"] = api_hash.strip()
    return out


async def full_deploy(token: str, variables: dict, repo: str = "", branch: str = "",
                      project_name: str = "tg-self", progress=None) -> dict:
    """کل مسیر دیپلوی؛ خروجی: {projectId, serviceId, environmentId, domain}."""
    repo = (repo or DEFAULT_REPO).strip()
    branch = (branch or DEFAULT_BRANCH).strip() or "main"

    async def say(t):
        if progress:
            try:
                await progress(t)
            except Exception:  # noqa
                pass

    await say("🔨 در حال ساخت پروژه...")
    pid = await create_project(token, project_name)
    await say("🌍 در حال پیدا کردن محیط production...")
    env_id = await get_production_env(token, pid)
    await say(f"📦 در حال اتصال ریپوی {repo}...")
    sid = await create_service(token, pid, repo, branch)
    await say("⚙️ در حال ست کردن متغیرها (PANEL_PASSWORD و...)...")
    await set_variables(token, pid, env_id, sid, variables)
    await say("💾 در حال ساخت Volume روی /data...")
    try:
        await create_volume(token, pid, sid, env_id, "/data")
    except RailwayError as e:
        await say("⚠️ " + str(e)[:200])
    await say("🌐 در حال گرفتن دامنه...")
    domain = await create_domain(token, sid, env_id)
    await say("🚀 در حال استارت دیپلوی...")
    try:
        await trigger_deploy(token, sid, env_id)
    except RailwayError as e:
        # بعضی‌وقت‌ها بعد از ساخت سرویس خودش دیپلوی می‌شه
        await say("ℹ️ تریگر دستی لازم نشد: " + str(e)[:150])
    await asyncio.sleep(1)
    return {"projectId": pid, "serviceId": sid, "environmentId": env_id, "domain": domain,
            "repo": repo, "branch": branch}
