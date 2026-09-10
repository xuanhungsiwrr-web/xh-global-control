"""Logical Master preference resolution over already-ranked channels."""

from collections.abc import Mapping, Sequence

from xh_control.config import SubscriptionConfig
from xh_control.exceptions import NoEligibleChannelError
from xh_control.models import ExecutionChannel, MasterPreference


PREFERENCE_SUBSCRIPTION = {
    MasterPreference.CLAUDE: "claude",
    MasterPreference.CHATGPT: "chatgpt",
}


class MasterSelector:
    """Honor a logical preference while retaining configured fallback policy."""

    def __init__(self, subscriptions: Mapping[str, SubscriptionConfig]) -> None:
        self.subscriptions = dict(subscriptions)

    def select(
        self,
        *,
        preference: MasterPreference,
        ranked_channels: Sequence[ExecutionChannel],
        all_channels: Mapping[str, ExecutionChannel],
        allow_cross_provider: bool,
    ) -> ExecutionChannel:
        if not ranked_channels:
            raise NoEligibleChannelError("No eligible execution channel")
        if preference == MasterPreference.AUTO:
            return ranked_channels[0]

        subscription_name = PREFERENCE_SUBSCRIPTION[preference]
        subscription = self.subscriptions.get(subscription_name)
        preferred_id = subscription.preferred_channel if subscription else None
        if preferred_id is not None:
            for channel in ranked_channels:
                if channel.channel_id == preferred_id:
                    return channel

        if allow_cross_provider:
            return ranked_channels[0]

        preferred_channel = all_channels.get(preferred_id) if preferred_id else None
        preferred_provider = preferred_channel.provider if preferred_channel else None
        same_provider = [
            channel
            for channel in ranked_channels
            if channel.provider == preferred_provider
        ]
        if same_provider:
            return same_provider[0]
        raise NoEligibleChannelError(
            f"No eligible {preference.value} channel and cross-provider fallback is disabled"
        )
