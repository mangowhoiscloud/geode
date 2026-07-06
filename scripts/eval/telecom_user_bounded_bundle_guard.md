User simulator bounded-bundle guard for telecom MMS diagnostics:
When the assistant asks for a prerequisite bundle, perform only the explicitly
requested safe phone-side tools in that bundle when possible, then provide one
concise consolidated status update.

Do not add extra troubleshooting branches. Do not call can_send_mms as part of
the prerequisite bundle. Do not use roaming, Wi-Fi calling, app-permission, or
escalation tools unless the assistant explicitly asks for that exact action or
the scenario requires it. If the assistant later asks for can_send_mms as a
separate terminal verification, perform that single verifier and report the
result.
