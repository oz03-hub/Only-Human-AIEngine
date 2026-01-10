from datetime import datetime, timedelta
from typing import List, Dict, Any

class TemporalFeatureExtractor:
    """Extract temporal features from conversation data for facilitation decision."""

    def __init__(self, messages: List[Dict[str, Any]], current_index: int):
        """
        Args:
            messages: List of message dictionaries with 'sender', 'time', 'content'
            current_index: Index of the current message to evaluate
        """
        self.messages = messages[:current_index + 1]  # Only consider messages up to current
        self.current_index = current_index
        self.timestamps = self._parse_timestamps()

    def _parse_timestamps(self) -> List[datetime]:
        """Parse time strings to datetime objects."""
        timestamps = []
        base_date = datetime(2024, 1, 1)  # Arbitrary base date

        for msg in self.messages:
            time_str = msg.get('time', '00:00')
            try:
                time_obj = datetime.strptime(time_str, '%H:%M')
                timestamp = base_date.replace(hour=time_obj.hour, minute=time_obj.minute)

                # Handle day rollover
                if timestamps and timestamp < timestamps[-1]:
                    base_date += timedelta(days=1)
                    timestamp = base_date.replace(hour=time_obj.hour, minute=time_obj.minute)

                timestamps.append(timestamp)
            except ValueError:
                # If parsing fails, use previous timestamp or base
                timestamps.append(timestamps[-1] if timestamps else base_date)

        return timestamps

    def get_messages_in_last_n_minutes(self, n: int) -> int:
        """Count messages in the last N minutes."""
        if not self.timestamps:
            return 0

        current_time = self.timestamps[self.current_index]
        cutoff = current_time - timedelta(minutes=n)

        count = 0
        for ts in self.timestamps:
            if ts >= cutoff:
                count += 1

        return count

    def get_messages_in_last_n_hours(self, n: int) -> int:
        """Count messages in the last N hours."""
        if not self.timestamps:
            return 0

        current_time = self.timestamps[self.current_index]
        cutoff = current_time - timedelta(hours=n)

        count = 0
        for ts in self.timestamps:
            if ts >= cutoff:
                count += 1

        return count

    def get_messages_today(self) -> int:
        """Count messages sent today (same day as current message)."""
        if not self.timestamps:
            return 0

        current_time = self.timestamps[self.current_index]
        current_day = current_time.date()

        count = 0
        for ts in self.timestamps:
            if ts.date() == current_day:
                count += 1

        return count

    def get_average_gap_last_n_messages(self, n: int) -> float:
        """Calculate average time gap (in minutes) between last N messages."""
        if len(self.timestamps) < 2:
            return 0.0

        # Get last n timestamps (or all if less than n)
        recent_timestamps = self.timestamps[-min(n, len(self.timestamps)):]

        if len(recent_timestamps) < 2:
            return 0.0

        gaps = []
        for i in range(1, len(recent_timestamps)):
            gap = (recent_timestamps[i] - recent_timestamps[i-1]).total_seconds() / 60
            gaps.append(gap)

        return sum(gaps) / len(gaps) if gaps else 0.0

    def get_unique_participants_last_n_messages(self, n: int) -> int:
        """Count unique participants in last N messages."""
        recent_messages = self.messages[-min(n, len(self.messages)):]
        unique_senders = set(msg['sender'] for msg in recent_messages)
        return len(unique_senders)

    def get_conversation_duration_hours(self) -> float:
        """Get total conversation duration in hours."""
        if len(self.timestamps) < 2:
            return 0.0

        duration = (self.timestamps[-1] - self.timestamps[0]).total_seconds() / 3600
        return duration

    def get_time_since_last_message_minutes(self) -> float:
        """Get time since previous message in minutes."""
        if self.current_index == 0:
            return 0.0

        gap = (self.timestamps[self.current_index] -
               self.timestamps[self.current_index - 1]).total_seconds() / 60
        return gap

    def extract_all_features(self) -> Dict[str, Any]:
        """Extract all temporal features."""
        return {
            'messages_last_30min': self.get_messages_in_last_n_minutes(30),
            'messages_last_hour': self.get_messages_in_last_n_hours(1),
            'messages_last_3hours': self.get_messages_in_last_n_hours(3),
            # 'messages_today': self.get_messages_today(),
            'avg_gap_last_5_messages_min': self.get_average_gap_last_n_messages(5),
            # 'avg_gap_last_10_messages_min': self.get_average_gap_last_n_messages(10),
            # 'unique_participants_last_5': self.get_unique_participants_last_n_messages(5),
            # 'unique_participants_last_10': self.get_unique_participants_last_n_messages(10),
            # 'conversation_duration_hours': self.get_conversation_duration_hours(),
            'time_since_last_message_min': self.get_time_since_last_message_minutes(),
            # 'total_messages': len(self.messages),
            # 'current_message_index': self.current_index
        }
