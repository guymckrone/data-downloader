"""StreamStats API client (stub).

I will grow this into real calls:
    snap(lat, lon) -> snapped point on the network
    watershed(lat, lon) / batch from a point list
    basin attributes for delineated pour points

No network traffic from this file yet — just the shape so the
StreamStats page and future code have a place to live.
"""


class StreamStatsClient:
    """Thin wrapper around USGS StreamStats services.

    Constructing this should stay cheap (like our data sources):
    don't hit the network until a method is called.
    """

    def __init__(self, timeout: int = 60):
        # timeout: StreamStats delineation can be slow.
        self.timeout = timeout

    def snap(self, latitude: float, longitude: float):
        """Snap a point to the StreamStats stream network.

        Not implemented yet.
        """
        raise NotImplementedError(
            "StreamStatsClient.snap() — next build step"
        )

    def watershed(self, latitude: float, longitude: float):
        """Delineate a watershed for one pour point.

        Not implemented yet.
        """
        raise NotImplementedError(
            "StreamStatsClient.watershed() — next build step"
        )

    def basin_attributes(self, workspace_id: str):
        """Fetch StreamStats characteristics for a workspace.

        Not implemented yet.
        """
        raise NotImplementedError(
            "StreamStatsClient.basin_attributes() — next build step"
        )
