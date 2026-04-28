"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Helpers for working with ``SecretStr`` typed fields on the client side.
Mirrors ``server.app.core.secrets`` — kept independent so the client
package has no import-time dependency on the server package.
"""

from typing import Optional, Union

from pydantic import SecretStr


def reveal(v: Union[SecretStr, str, None]) -> Optional[str]:
    """Return the underlying string of a ``SecretStr`` (or pass through ``str``).

    Accepting both ``SecretStr`` and plain ``str`` keeps tests, monkeypatches,
    and any transitional call sites working during migration without
    forcing every read site to switch in lockstep.
    """
    if isinstance(v, SecretStr):
        return v.get_secret_value()
    return v
