import d from "dayjs"
import localizedFormat from "dayjs/plugin/localizedFormat"
import relativeTime from "dayjs/plugin/relativeTime"

d.extend(localizedFormat)
d.extend(relativeTime)

// Custom format methods (matching helpdesk pattern)
d.extend(function (_, cls) {
	cls.prototype.short = function () {
		return this.format("MMM D, h:mm A")  // Example: "Feb 2, 11:30 AM"
	}
	cls.prototype.long = function () {
		return this.format("LLLL")  // Example: "Sunday, February 2, 2026 11:30 AM"
	}
})

export const dayjs = d
