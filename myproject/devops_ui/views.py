import logging
import re
from urllib.parse import quote

import requests
from requests.auth import HTTPBasicAuth

from django.conf import settings
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)

# Validators
_PIPELINE_ID_RE = re.compile(r"^\d+$")  # Azure DevOps pipeline IDs are integers


def _safe_json(resp):
    """
    Return JSON if possible; otherwise a trimmed text fallback.
    Avoids exceptions on empty/invalid JSON responses.
    """
    try:
        if (resp.text or "").strip() == "":
            return {}
        return resp.json()
    except ValueError:
        # Avoid excessive memory/logging on huge bodies
        return {"raw": (resp.text or "")[:2000]}


def _trigger_devops_run(pipeline_id: str, project: str, ref_name: str):
    """
    Triggers an Azure DevOps pipeline run.

    Raises:
        RuntimeError: When essential configuration is missing.
        requests.exceptions.RequestException: For network-level issues.

    Returns:
        (status_code: int, body: dict|str)
    """
    if not settings.AZDO_ORG_URL or not settings.AZDO_PAT:
        raise RuntimeError("Azure DevOps configuration missing (AZDO_ORG_URL or AZDO_PAT).")

    # URL-encode the project segment so names with spaces/special chars work.
    project_segment = quote(project, safe="")  # safe='' encodes all reserved chars (we also block '/')

    url = (
        f"{settings.AZDO_ORG_URL.rstrip('/')}/"
        f"{project_segment}/_apis/pipelines/{pipeline_id}/runs?api-version=7.1"
    )
    payload = {"resources": {"repositories": {"self": {"refName": ref_name}}}}

    # Azure DevOps uses PAT as Basic auth password with empty username
    auth = HTTPBasicAuth("", settings.AZDO_PAT)

    # Reasonable timeout to avoid hanging requests
    resp = requests.post(url, auth=auth, json=payload, timeout=15)
    body = _safe_json(resp)
    return resp.status_code, body


@require_http_methods(["GET", "POST"])
def devops_trigger(request):
    """
    Simple form to trigger an Azure DevOps pipeline by ID + project + ref.
    Expects the following settings to be present (typically from .env via python-decouple):
      - AZDO_ORG_URL (e.g., https://dev.azure.com/YourOrg)
      - AZDO_PAT
      - AZDO_DEFAULT_PROJECT (optional)
      - AZDO_DEFAULT_REF (optional; default falls back to 'refs/heads/main')
    """
    default_ref = getattr(settings, "AZDO_DEFAULT_REF", None) or "refs/heads/main"
    default_project = getattr(settings, "AZDO_DEFAULT_PROJECT", "")

    context = {
        "default_project": default_project,
        "default_ref": default_ref,
    }

    if request.method == "POST":
        pipeline_id = (request.POST.get("pipelineId") or "").strip()
        project = (request.POST.get("project") or "").strip() or default_project
        ref_name = (request.POST.get("refName") or "").strip() or default_ref

        context.update(
            {
                "pipelineId": pipeline_id,
                "project": project,
                "refName": ref_name,
            }
        )

        # Input validation
        errors = []
        if not pipeline_id or not _PIPELINE_ID_RE.match(pipeline_id):
            errors.append("Pipeline ID must be a numeric ID (e.g., 42).")

        # Project can contain spaces and most characters; only disallow '/' which breaks the URL path.
        if not project:
            errors.append("Project is required.")
        elif "/" in project:
            errors.append("Project must not contain '/'. Use the exact display name from Azure DevOps.")

        if not ref_name.startswith("refs/"):
            errors.append("Branch must be a valid Git ref (e.g., refs/heads/main).")

        if errors:
            context["error"] = " ".join(errors)
            return render(request, "devops_ui/trigger.html", context)

        try:
            status, body = _trigger_devops_run(pipeline_id, project, ref_name)
            context["result"] = {"status": status, "body": body}

            # Minimal, safe logging (never log PAT/headers/body).
            logger.info(
                "Triggered Azure DevOps pipeline: project=%s pipeline_id=%s status=%s",
                project,
                pipeline_id,
                status,
            )

            if status >= 400:
                context["error"] = (
                    f"Azure DevOps returned HTTP {status}. "
                    f"Check pipeline ID, project name, branch ref, permissions, and PAT scopes."
                )

        except requests.exceptions.Timeout:
            context["error"] = "Request to Azure DevOps timed out. Please retry."
            logger.warning(
                "Timeout triggering pipeline: project=%s pipeline_id=%s", project, pipeline_id
            )
        except requests.exceptions.RequestException as e:
            context["error"] = f"Network error while contacting Azure DevOps: {str(e)}"
            logger.exception(
                "Network error triggering pipeline: project=%s pipeline_id=%s", project, pipeline_id
            )
        except RuntimeError as e:
            context["error"] = str(e)
            logger.error("Configuration error: %s", e)

    return render(request, "devops_ui/trigger.html", context)
