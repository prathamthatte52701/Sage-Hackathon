from routers.projects import router


def test_v1_does_not_register_automation_routes():
    # V2_AUTOMATION_DISABLED:
    # Automation is intentionally excluded from CODE MASTER AI V1.
    # Preserve this code for the V2 automation workflow.
    routes = {route.path for route in router.routes}
    assert "/projects/{project_id}/automation" not in routes
    assert "/projects/{project_id}/automation/status" not in routes
    assert "/projects/{project_id}/automation/stop" not in routes
