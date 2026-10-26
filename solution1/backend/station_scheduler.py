"""按工位独立预约时间片：本次交付相对旧原型的核心修改点。

旧原型 earliest 取全局 MAX(end_s)，把 S1/S2 串成一条时间轴，
吞吐减半；这里改为只看本工位的 MAX(end_s)。
"""


class StationScheduler:
    def __init__(self, store):
        self.store = store

    def earliest(self, ready_s, station_id):
        previous_end = self.store.station_last_end(station_id)
        return max(ready_s, previous_end), previous_end
