<template>
	<Dialog v-model="ctx.showNotificationDialog.value" :options="{ title: 'Link Notification', size: '5xl' }">
		<template #body-content>
			<div class="space-y-4">
				<!-- Mode Tabs -->
				<div class="flex border-b border-gray-200">
					<button
						@click="ctx.notifDialogMode.value = 'select'"
						:class="[
							'px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px',
							ctx.notifDialogMode.value === 'select'
								? 'border-blue-500 text-blue-600'
								: 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
						]"
					>
						<Icon icon="lucide:search" class="w-4 h-4 inline mr-1.5" />
						Select Existing
					</button>
					<button
						@click="ctx.notifDialogMode.value = 'create'"
						:class="[
							'px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px',
							ctx.notifDialogMode.value === 'create'
								? 'border-blue-500 text-blue-600'
								: 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
						]"
					>
						<Icon icon="lucide:plus" class="w-4 h-4 inline mr-1.5" />
						Create New
					</button>
				</div>

				<!-- ========== Select Existing Mode ========== -->
				<div v-if="ctx.notifDialogMode.value === 'select'" class="space-y-3">
					<div class="text-sm text-gray-500">
						Search and select an existing Notification to link.
					</div>
					<div class="grid grid-cols-2 gap-3">
						<div class="relative">
							<Icon icon="lucide:search" class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
							<input
								v-model="ctx.notifSearch.value"
								type="text"
								placeholder="Search notifications..."
								class="w-full pl-10 pr-3 py-2 border border-gray-300 rounded-lg text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-blue-400"
							/>
						</div>
						<div class="relative">
							<input
								v-model="ctx.notifDoctypeFilter.value"
								type="text"
								placeholder="Filter by Document Type..."
								class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-blue-400"
								@focus="ctx.showNotifDoctypeDropdown.value = true"
								@blur="setTimeout(() => ctx.showNotifDoctypeDropdown.value = false, 200)"
							/>
							<button
								v-if="ctx.notifDoctypeFilter.value"
								@click="ctx.notifDoctypeFilter.value = ''"
								class="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
							>
								<Icon icon="lucide:x" class="w-4 h-4" />
							</button>
							<div v-if="ctx.showNotifDoctypeDropdown.value && ctx.filteredNotifDoctypeOptions.value.length > 0" class="absolute z-50 w-full mt-1 max-h-48 overflow-y-auto bg-white border border-gray-200 rounded-md shadow-lg">
								<div
									v-for="dt in ctx.filteredNotifDoctypeOptions.value"
									:key="dt"
									@mousedown.prevent="ctx.notifDoctypeFilter.value = dt; ctx.showNotifDoctypeDropdown.value = false"
									class="px-3 py-1.5 text-sm cursor-pointer hover:bg-blue-50 text-gray-900"
								>{{ dt }}</div>
							</div>
						</div>
					</div>
					<div class="max-h-72 overflow-y-auto border border-gray-200 rounded-lg">
						<div v-if="ctx.loadingNotifications.value" class="p-6 text-center text-gray-400">
							<div class="animate-spin rounded-full h-6 w-6 border-b-2 border-gray-400 mx-auto mb-2"></div>
							Loading notifications...
						</div>
						<div v-else-if="ctx.filteredNotifications.value.length === 0" class="p-6 text-center text-gray-400">
							No notifications found.
						</div>
						<div
							v-else
							v-for="notif in ctx.filteredNotifications.value"
							:key="notif.name"
							@click="ctx.selectedNotification.value = notif.name"
							:class="[
								'flex items-center justify-between px-4 py-3 cursor-pointer border-b border-gray-100 last:border-b-0 transition-colors',
								ctx.selectedNotification.value === notif.name
									? 'bg-blue-50 border-l-4 border-l-blue-500'
									: 'hover:bg-gray-50'
							]"
						>
							<div>
								<div class="text-sm font-medium text-gray-900">
									<span class="mr-1.5">{{ ctx.channelIcon(notif.channel) }}</span>
									{{ notif.name }}
								</div>
								<div class="text-xs text-gray-500 mt-0.5">
									{{ notif.channel }}
									<span v-if="notif.document_type"> · {{ notif.document_type }}</span>
									<span v-if="notif.subject"> · {{ notif.subject }}</span>
								</div>
							</div>
							<div class="flex items-center gap-2">
								<span v-if="!notif.enabled" class="text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full">Disabled</span>
								<span v-else class="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">Enabled</span>
								<Icon v-if="ctx.selectedNotification.value === notif.name" icon="lucide:check-circle" class="w-5 h-5 text-blue-500" />
							</div>
						</div>
					</div>
				</div>

				<!-- ========== Create New Mode ========== -->
				<div v-else-if="ctx.notifDialogMode.value === 'create'" class="space-y-4">
					<div class="text-sm text-gray-500">
						Create a new Notification and link it to this Send Task.
						It will be <strong>disabled</strong> by default.
					</div>

					<div class="grid grid-cols-2 gap-4">
						<div>
							<label class="block text-xs font-medium text-gray-700 mb-1">Notification Name <span class="text-red-500">*</span></label>
							<input v-model="ctx.newNotif.value.name" type="text" placeholder="e.g. Order Confirmation Email" class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400" />
						</div>
						<div>
							<label class="block text-xs font-medium text-gray-700 mb-1">Channel <span class="text-red-500">*</span></label>
							<select v-model="ctx.newNotif.value.channel" class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400">
								<option value="">Select channel...</option>
								<option value="Email">📧 Email</option>
								<option value="System Notification">🔔 System Notification</option>
								<option value="WhatsApp">💬 WhatsApp</option>
								<option value="SMS">📱 SMS</option>
								<option value="Slack">🔗 Slack</option>
							</select>
						</div>
					</div>

					<div class="grid grid-cols-2 gap-4">
						<div>
							<label class="block text-xs font-medium text-gray-700 mb-1">Send Alert On <span class="text-red-500">*</span></label>
							<select v-model="ctx.newNotif.value.event" class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400">
								<option value="">Select event...</option>
								<option v-for="evt in ctx.notifEvents" :key="evt" :value="evt">{{ evt }}</option>
							</select>
						</div>
						<div>
							<label class="block text-xs font-medium text-gray-700 mb-1">Document Type <span class="text-red-500">*</span></label>
							<div class="relative">
								<input v-model="ctx.notifNewDoctypeSearch.value" type="text" :placeholder="ctx.newNotif.value.document_type || 'Search DocType...'" class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400" @focus="ctx.showNotifNewDoctypeDropdown.value = true; ctx.notifNewDoctypeSearch.value = ''" @blur="setTimeout(() => ctx.showNotifNewDoctypeDropdown.value = false, 200)" />
								<div v-if="ctx.showNotifNewDoctypeDropdown.value && ctx.filteredNotifNewDoctypeOptions.value.length > 0" class="absolute z-50 w-full mt-1 max-h-48 overflow-y-auto bg-white border border-gray-200 rounded-md shadow-lg">
									<div v-for="dt in ctx.filteredNotifNewDoctypeOptions.value" :key="dt" @mousedown.prevent="ctx.newNotif.value.document_type = dt; ctx.notifNewDoctypeSearch.value = dt; ctx.showNotifNewDoctypeDropdown.value = false" class="px-3 py-1.5 text-sm cursor-pointer hover:bg-blue-50 text-gray-900">{{ dt }}</div>
								</div>
							</div>
						</div>
					</div>

					<!-- Trigger Fields -->
					<div v-if="ctx.newNotif.value.event === 'Method'" class="grid grid-cols-2 gap-4">
						<div>
							<label class="block text-xs font-medium text-gray-700 mb-1">Trigger Method</label>
							<input v-model="ctx.newNotif.value.method" type="text" placeholder="e.g. my_module.my_method" class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400" />
						</div>
					</div>
					<div v-if="['Days After', 'Days Before'].includes(ctx.newNotif.value.event)" class="grid grid-cols-2 gap-4">
						<div>
							<label class="block text-xs font-medium text-gray-700 mb-1">Reference Date</label>
							<input v-model="ctx.newNotif.value.date_changed" type="text" placeholder="e.g. due_date" class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400" />
						</div>
						<div>
							<label class="block text-xs font-medium text-gray-700 mb-1">Days Before or After</label>
							<input v-model="ctx.newNotif.value.days_in_advance" type="number" min="0" class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400" />
						</div>
					</div>
					<div v-if="ctx.newNotif.value.event === 'Value Change'" class="grid grid-cols-2 gap-4">
						<div>
							<label class="block text-xs font-medium text-gray-700 mb-1">Value Changed</label>
							<input v-model="ctx.newNotif.value.value_changed" type="text" placeholder="e.g. status" class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400" />
						</div>
					</div>

					<div>
						<label class="block text-xs font-medium text-gray-700 mb-1">Subject</label>
						<input v-model="ctx.newNotif.value.subject" type="text" placeholder="e.g. New {{ doc.doctype }} Created" class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400" />
					</div>
					<div>
						<label class="block text-xs font-medium text-gray-700 mb-1">Condition</label>
						<input v-model="ctx.newNotif.value.condition" type="text" placeholder='e.g. doc.status=="Open"' class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400" />
					</div>

					<!-- Channel-specific -->
					<div v-if="ctx.newNotif.value.channel === 'Email'" class="grid grid-cols-2 gap-4">
						<div>
							<label class="block text-xs font-medium text-gray-700 mb-1">Sender (Email Account)</label>
							<input v-model="ctx.newNotif.value.sender" type="text" placeholder="Email Account name" class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400" />
						</div>
						<div>
							<label class="block text-xs font-medium text-gray-700 mb-1">Sender Email</label>
							<input v-model="ctx.newNotif.value.sender_email" type="email" placeholder="noreply@example.com" class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400" />
						</div>
					</div>
					<div v-if="ctx.newNotif.value.channel === 'Slack'">
						<label class="block text-xs font-medium text-gray-700 mb-1">Slack Webhook URL</label>
						<input v-model="ctx.newNotif.value.slack_webhook_url" type="text" placeholder="Slack Webhook URL record name" class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400" />
					</div>
					<div v-if="ctx.newNotif.value.channel === 'WhatsApp'">
						<label class="block text-xs font-medium text-gray-700 mb-1">Twilio Number (Communication Medium)</label>
						<input v-model="ctx.newNotif.value.twilio_number" type="text" placeholder="Communication Medium record name" class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400" />
					</div>
					<div v-if="ctx.newNotif.value.channel === 'Email'" class="flex items-center gap-4">
						<label class="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
							<input type="checkbox" v-model="ctx.newNotif.value.send_system_notification" class="rounded border-gray-300" />
							Also Send System Notification
						</label>
					</div>

					<!-- Recipients -->
					<div class="border border-gray-200 rounded-lg p-3 space-y-3">
						<div class="flex items-center justify-between">
							<label class="text-xs font-semibold text-gray-700 uppercase tracking-wide">Recipients</label>
							<button @click="ctx.addRecipientRow()" type="button" class="text-xs text-blue-600 hover:text-blue-700 font-medium">+ Add Row</button>
						</div>
						<label class="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
							<input type="checkbox" v-model="ctx.newNotif.value.send_to_all_assignees" class="rounded border-gray-300" />
							Send To All Assignees
						</label>
						<div v-for="row in ctx.newNotif.value.recipients" :key="row._id" class="grid grid-cols-6 gap-2 items-end border-t border-gray-100 pt-2">
							<div>
								<label class="block text-xs text-gray-500 mb-0.5">By Document Field</label>
								<input v-model="row.receiver_by_document_field" type="text" placeholder="e.g. owner" class="w-full px-2 py-1 border border-gray-300 rounded text-xs bg-white text-gray-900 focus:outline-none focus:ring-1 focus:ring-blue-400" />
							</div>
							<div>
								<label class="block text-xs text-gray-500 mb-0.5">By Role</label>
								<input v-model="row.receiver_by_role" type="text" placeholder="e.g. HR Manager" class="w-full px-2 py-1 border border-gray-300 rounded text-xs bg-white text-gray-900 focus:outline-none focus:ring-1 focus:ring-blue-400" />
							</div>
							<div>
								<label class="block text-xs text-gray-500 mb-0.5">CC</label>
								<input v-model="row.cc" type="text" placeholder="cc@example.com" class="w-full px-2 py-1 border border-gray-300 rounded text-xs bg-white text-gray-900 focus:outline-none focus:ring-1 focus:ring-blue-400" />
							</div>
							<div>
								<label class="block text-xs text-gray-500 mb-0.5">BCC</label>
								<input v-model="row.bcc" type="text" placeholder="bcc@example.com" class="w-full px-2 py-1 border border-gray-300 rounded text-xs bg-white text-gray-900 focus:outline-none focus:ring-1 focus:ring-blue-400" />
							</div>
							<div>
								<label class="block text-xs text-gray-500 mb-0.5">Condition</label>
								<input v-model="row.condition" type="text" placeholder='doc.status=="Open"' class="w-full px-2 py-1 border border-gray-300 rounded text-xs bg-white text-gray-900 focus:outline-none focus:ring-1 focus:ring-blue-400" />
							</div>
							<div class="flex items-end">
								<button @click="ctx.removeRecipientRow(ctx.newNotif.value.recipients.indexOf(row))" type="button" class="p-1 text-red-400 hover:text-red-600 transition-colors" title="Remove row">
									<Icon icon="lucide:trash-2" class="w-4 h-4" />
								</button>
							</div>
						</div>
					</div>

					<!-- Message -->
					<div class="grid grid-cols-4 gap-4">
						<div class="col-span-1">
							<label class="block text-xs font-medium text-gray-700 mb-1">Message Type</label>
							<select v-model="ctx.newNotif.value.message_type" class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400">
								<option value="Markdown">Markdown</option>
								<option value="HTML">HTML</option>
								<option value="Plain Text">Plain Text</option>
							</select>
						</div>
						<div class="col-span-1" v-if="ctx.newNotif.value.channel === 'Email'">
							<label class="block text-xs font-medium text-gray-700 mb-1">Module</label>
							<div class="relative">
								<input v-model="ctx.notifModuleSearch.value" type="text" :placeholder="ctx.newNotif.value.module || 'Search Module...'" class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400" @focus="ctx.showNotifModuleDropdown.value = true; ctx.notifModuleSearch.value = ''" @blur="setTimeout(() => ctx.showNotifModuleDropdown.value = false, 200)" />
								<div v-if="ctx.showNotifModuleDropdown.value && ctx.filteredNotifModuleOptions.value.length > 0" class="absolute z-50 w-full mt-1 max-h-48 overflow-y-auto bg-white border border-gray-200 rounded-md shadow-lg">
									<div v-for="mod in ctx.filteredNotifModuleOptions.value" :key="mod" @mousedown.prevent="ctx.newNotif.value.module = mod; ctx.notifModuleSearch.value = mod; ctx.showNotifModuleDropdown.value = false" class="px-3 py-1.5 text-sm cursor-pointer hover:bg-blue-50 text-gray-900">{{ mod }}</div>
								</div>
							</div>
						</div>
					</div>
					<div>
						<label class="block text-xs font-medium text-gray-700 mb-1">Message</label>
						<textarea v-model="ctx.newNotif.value.message" class="w-full h-32 p-3 font-mono text-sm border border-gray-300 rounded-lg bg-gray-50 text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-blue-400 resize-y" placeholder="Enter message template (Jinja supported)..." spellcheck="false"></textarea>
					</div>

					<!-- Print Settings -->
					<div v-if="ctx.newNotif.value.channel === 'Email'" class="grid grid-cols-2 gap-4">
						<label class="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
							<input type="checkbox" v-model="ctx.newNotif.value.attach_print" class="rounded border-gray-300" />
							Attach Print
						</label>
						<div v-if="ctx.newNotif.value.attach_print">
							<label class="block text-xs font-medium text-gray-700 mb-1">Print Format</label>
							<input v-model="ctx.newNotif.value.print_format" type="text" placeholder="Print Format name" class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400" />
						</div>
					</div>

					<!-- After Alert -->
					<div class="grid grid-cols-2 gap-4">
						<div>
							<label class="block text-xs font-medium text-gray-700 mb-1">Set Property After Alert</label>
							<input v-model="ctx.newNotif.value.set_property_after_alert" type="text" placeholder="e.g. notification_sent" class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400" />
						</div>
						<div v-if="ctx.newNotif.value.set_property_after_alert">
							<label class="block text-xs font-medium text-gray-700 mb-1">Value To Be Set</label>
							<input v-model="ctx.newNotif.value.property_value" type="text" placeholder="e.g. 1" class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400" />
						</div>
					</div>
				</div>
			</div>
		</template>
		<template #actions>
			<div class="flex gap-2">
				<Button variant="subtle" @click="ctx.showNotificationDialog.value = false">Cancel</Button>
				<Button
					v-if="ctx.notifDialogMode.value === 'select'"
					variant="solid"
					@click="ctx.linkNotification()"
					:disabled="!ctx.selectedNotification.value"
				>Link Notification</Button>
				<Button
					v-else
					variant="solid"
					@click="ctx.createAndLinkNotification()"
					:loading="ctx.creatingNotification.value"
					:disabled="!ctx.newNotif.value.name || !ctx.newNotif.value.channel || !ctx.newNotif.value.document_type"
				>Create & Link</Button>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import { inject } from "vue";
import { Icon } from "@iconify/vue";

// Inject the composable instance provided by Editor.vue
const ctx = inject("notifDialog");
</script>
