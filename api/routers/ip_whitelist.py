from sqlalchemy.orm import Session
from sqlalchemy import text


def check_ip_whitelist(api_key: str, request_ip: str, db: Session) -> bool:
    """
    Check whether the request IP is permitted for the given API key.

    Lookup flow:
      1. Resolve the api_key string to a user_id via the api_keys table.
      2. Look up the user's registered allowed IP in user_allowed_ips.
      3. If no allowed IP is registered, permit all IPs (return True).
      4. If an allowed IP exists, compare it against the request IP.
         Return True on match, False on mismatch.

    Returns:
        True  — request is allowed to proceed
        False — request should be rejected with 403
    """
    # Step 1: resolve api_key → user_id
    key_row = db.execute(
        text("SELECT user_id FROM api_keys WHERE `key` = :key"),
        {"key": api_key},
    ).fetchone()

    # Key not found — treated as unauthenticated; let the existing
    # 401 logic in verify_api_key handle it rather than raising here.
    if key_row is None:
        return True

    user_id = key_row[0]

    # Step 2: look up the user's registered allowed IP
    ip_row = db.execute(
        text("SELECT ip_address FROM user_allowed_ips WHERE user_id = :uid"),
        {"uid": user_id},
    ).fetchone()

    # Step 3: no IP registered — permit all origins
    if ip_row is None:
        return True

    # Step 4: compare registered IP against the actual request IP
    registered_ip = ip_row[0]
    return request_ip == registered_ip