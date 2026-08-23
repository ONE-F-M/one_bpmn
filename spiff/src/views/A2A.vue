<template>
	<div class="h-full flex flex-col bg-gray-50">
		<header class="bg-white border-b px-6 py-4">
			<div class="flex items-center justify-between">
				<div>
					<h1 class="text-xl font-semibold text-gray-900">Agent Collaboration (A2A)</h1>
					<p class="text-xs text-gray-500 mt-0.5">
						Who we may delegate to, who may call us, and what is in flight either way.
					</p>
				</div>
				<nav class="flex gap-1 bg-gray-100 rounded-lg p-1">
					<button
						v-for="t in tabs"
						:key="t.key"
						class="px-3 py-1.5 text-sm rounded-md transition-colors"
						:class="tab === t.key ? 'bg-white shadow-sm font-medium text-gray-900' : 'text-gray-600 hover:text-gray-900'"
						@click="tab = t.key"
					>
						{{ t.label }}
						<span v-if="t.count !== null" class="ml-1 text-xs text-gray-400">{{ t.count }}</span>
					</button>
				</nav>
			</div>
		</header>

		<ErrorMessage v-if="error" :message="error" class="mx-6 mt-4" />

		<div v-if="!can.administer" class="m-6 text-sm text-gray-600">
			Administering agent collaboration needs the System Manager role.
		</div>

		<!-- Our agents (what we publish) -->
		<div v-else-if="tab === 'ours'" class="flex-1 overflow-auto px-6 py-4">
			<p class="text-sm text-gray-600 mb-3">
				Every agent ticked <strong>Exposed over A2A</strong>, with the card the world would
				fetch. A card is public; this list is not — it stays behind admin access so nobody
				outside gets a directory of our agents.
			</p>
			<div v-if="loading.ours" class="text-sm text-gray-500">Loading…</div>
			<table v-else class="w-full text-sm bg-white rounded-lg overflow-hidden">
				<thead class="bg-gray-100 text-left text-xs uppercase text-gray-500">
					<tr>
						<th class="px-4 py-2">Agent</th>
						<th class="px-4 py-2">Tags</th>
						<th class="px-4 py-2">Reachable by</th>
						<th class="px-4 py-2 text-right">Card</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="a in ourAgents" :key="a.agent_id" class="border-t">
						<td class="px-4 py-2">
							<div class="font-medium text-gray-900">{{ a.agent_name }}</div>
							<div class="text-xs text-gray-500">{{ a.agent_id }} · {{ a.agent_type }}</div>
						</td>
						<td class="px-4 py-2">
							<span
								v-for="t in a.tags"
								:key="t"
								class="inline-block mr-1 mb-1 px-2 py-0.5 text-xs rounded-full bg-gray-100 text-gray-700"
							>
								{{ t }}
							</span>
							<span v-if="!a.tags.length" class="text-gray-400 text-xs">no tags</span>
						</td>
						<td class="px-4 py-2 text-gray-600">
							<span v-if="a.reachable_by.length">{{ a.reachable_by.join(", ") }}</span>
							<span v-else class="text-gray-400" title="Its card is public, but no approved client lists it">
								nobody outside
							</span>
						</td>
						<td class="px-4 py-2 text-right whitespace-nowrap">
							<Button variant="ghost" @click="copyCardUrl(a)">
								{{ copied === a.agent_id ? "Copied" : "Copy link" }}
							</Button>
							<Button variant="ghost" @click="showCard(a)">View</Button>
						</td>
					</tr>
					<tr v-if="!ourAgents.length">
						<td colspan="4" class="px-4 py-6 text-center text-gray-500">
							No agents are exposed yet. Tick “Exposed over A2A” on an enabled, Live agent.
						</td>
					</tr>
				</tbody>
			</table>
		</div>

		<!-- Remote agents (outbound) -->
		<div v-else-if="tab === 'remotes'" class="flex-1 overflow-auto px-6 py-4">
			<div class="flex items-start justify-between gap-4 mb-3">
				<p class="text-sm text-gray-600">
					Our processes may delegate only to an entry that is enabled and approved. Fetch the
					card first — the card is what you are approving. Changing an endpoint sends the
					entry back to Draft.
				</p>
				<Button variant="solid" @click="openRemoteForm()">New remote agent</Button>
			</div>
			<div v-if="loading.remotes" class="text-sm text-gray-500">Loading…</div>
			<table v-else class="w-full text-sm bg-white rounded-lg overflow-hidden">
				<thead class="bg-gray-100 text-left text-xs uppercase text-gray-500">
					<tr>
						<th class="px-4 py-2">Agent</th>
						<th class="px-4 py-2">Endpoint</th>
						<th class="px-4 py-2">Card</th>
						<th class="px-4 py-2">Status</th>
						<th class="px-4 py-2 text-right">Actions</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in remotes" :key="r.name" class="border-t">
						<td class="px-4 py-2 font-medium text-gray-900">
							{{ r.agent_name }}
							<span v-if="!r.enabled" class="ml-1 text-xs text-gray-400">(disabled)</span>
						</td>
						<td class="px-4 py-2 text-gray-600 truncate max-w-xs">{{ r.endpoint_url }}</td>
						<td class="px-4 py-2 text-gray-600">
							<span v-if="r.card_name">{{ r.card_name }}</span>
							<span v-else class="text-gray-400">not fetched</span>
						</td>
						<td class="px-4 py-2">
							<Badge :theme="statusTheme(r.approval_status)">{{ r.approval_status }}</Badge>
						</td>
						<td class="px-4 py-2 text-right whitespace-nowrap">
							<Button variant="ghost" @click="openRemoteForm(r)">Edit</Button>
							<Button variant="ghost" @click="fetchCard(r)">Fetch card</Button>
							<Button
								v-if="r.approval_status !== 'Approved'"
								variant="ghost"
								:disabled="!r.card_name"
								@click="setRemote(r, 'Approved')"
							>
								Approve
							</Button>
							<Button v-else variant="ghost" @click="setRemote(r, 'Revoked')">Revoke</Button>
						</td>
					</tr>
					<tr v-if="!remotes.length">
						<td colspan="5" class="px-4 py-6 text-center text-gray-500">
							No remote agents registered yet.
						</td>
					</tr>
				</tbody>
			</table>
		</div>

		<!-- Clients (inbound) -->
		<div v-else-if="tab === 'clients'" class="flex-1 overflow-auto px-6 py-4">
			<div class="flex items-start justify-between gap-4 mb-3">
				<p class="text-sm text-gray-600">
					Every caller is one entry with its own key and its own list of agents. Approving
					issues the key; revoking stops that caller alone.
				</p>
				<Button variant="solid" @click="openClientForm()">New client</Button>
			</div>
			<div v-if="loading.clients" class="text-sm text-gray-500">Loading…</div>
			<table v-else class="w-full text-sm bg-white rounded-lg overflow-hidden">
				<thead class="bg-gray-100 text-left text-xs uppercase text-gray-500">
					<tr>
						<th class="px-4 py-2">Client</th>
						<th class="px-4 py-2">Service user</th>
						<th class="px-4 py-2">May call</th>
						<th class="px-4 py-2">Status</th>
						<th class="px-4 py-2 text-right">Actions</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="c in clients" :key="c.name" class="border-t">
						<td class="px-4 py-2 font-medium text-gray-900">
							{{ c.client_name }}
							<span v-if="!c.enabled" class="ml-1 text-xs text-gray-400">(disabled)</span>
						</td>
						<td class="px-4 py-2 text-gray-600">
							{{ c.user || "—" }}
						</td>
						<td class="px-4 py-2 text-gray-600">
							<span v-if="c.allowed_agents.length">{{ c.allowed_agents.join(", ") }}</span>
							<span v-else class="text-gray-400">nothing</span>
						</td>
						<td class="px-4 py-2">
							<Badge :theme="statusTheme(c.approval_status)">{{ c.approval_status }}</Badge>
						</td>
						<td class="px-4 py-2 text-right whitespace-nowrap">
							<Button variant="ghost" @click="openClientAgents(c)">Agents</Button>
							<Button
								v-if="c.approval_status !== 'Approved'"
								variant="ghost"
								@click="setClient(c, 'Approved')"
							>
								Approve
							</Button>
							<template v-else>
								<Button variant="ghost" @click="showCredentials(c)">Credentials</Button>
								<Button variant="ghost" @click="setClient(c, 'Revoked')">Revoke</Button>
							</template>
						</td>
					</tr>
					<tr v-if="!clients.length">
						<td colspan="5" class="px-4 py-6 text-center text-gray-500">
							No clients registered yet.
						</td>
					</tr>
				</tbody>
			</table>
		</div>

		<!-- Delegations: the same hand-off, seen from the work it was for -->
		<div v-else-if="tab === 'delegations'" class="flex-1 flex flex-col overflow-hidden">
			<div class="bg-white px-6 py-3 border-b flex flex-wrap gap-3 items-center">
				<FormControl
					type="text"
					v-model="dFilters.a2a_task"
					placeholder="Task, e.g. A2A-17522"
					class="w-52"
				/>
				<FormControl
					type="select"
					v-model="dFilters.reference_doctype"
					:options="doctypeOptions"
					class="w-48"
					@change="loadDelegations(0)"
				/>
				<FormControl
					type="text"
					v-model="dFilters.reference_name"
					placeholder="Document, e.g. WI-0028"
					class="w-52"
				/>
				<FormControl
					type="select"
					v-model="dFilters.status"
					:options="delegationStatusOptions"
					class="w-48"
					@change="loadDelegations(0)"
				/>
				<Button v-if="anyDelegationFilter" variant="ghost" @click="resetDelegationFilters">
					Clear filters
				</Button>
				<div class="ml-auto flex items-center gap-4">
					<span class="text-sm text-gray-600">{{ dTotal }} delegations</span>
				<div class="flex items-center gap-2">
					<span class="text-sm text-gray-600">Page Size:</span>
					<FormControl
						type="select"
						v-model="pageLength"
						:options="pageSizeOptions"
						class="w-20"
						@change="changePageSize"
					/>
				</div>
				</div>
			</div>
			<div class="flex-1 overflow-auto px-6 py-4">
				<p class="text-sm text-gray-600 mb-3">
					Who is working on what, and how far along. A delegation that stopped at a limit
					stays here with the limit that stopped it — click a row for the whole story.
				</p>
				<div v-if="loading.delegations" class="text-sm text-gray-500">Loading…</div>
				<table v-else class="w-full text-sm bg-white rounded-lg overflow-hidden">
					<thead class="bg-gray-100 text-left text-xs uppercase text-gray-500">
						<tr>
							<th class="px-4 py-2">Work</th>
							<th class="px-4 py-2" title="The agent that handed the work over">Delegated by</th>
							<th class="px-4 py-2" title="The agent doing the work">Handled by</th>
							<th class="px-4 py-2">Status</th>
							<th class="px-4 py-2" title="The limit that stopped it, if one did">Stopped at</th>
							<th class="px-4 py-2" title="Nesting depth / hand-offs / attempts">D / H / A</th>
							<th class="px-4 py-2">Last updated</th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="d in delegations"
							:key="d.name"
							class="border-t cursor-pointer hover:bg-gray-50"
							@click="openDelegation(d)"
						>
							<td class="px-4 py-2">
								<div class="font-medium text-gray-900">
									{{ d.reference_name || "—" }}
								</div>
								<div class="text-xs text-gray-500">
									{{ d.reference_doctype || "nothing linked" }}
								</div>
							</td>
							<td class="px-4 py-2 text-gray-600">{{ d.delegating_agent || "—" }}</td>
							<td class="px-4 py-2 text-gray-600">{{ d.worker_agent || "—" }}</td>
							<td class="px-4 py-2">
								<Badge :theme="delegationTheme(d.status)">{{ d.status }}</Badge>
							</td>
							<td class="px-4 py-2 text-gray-600 text-xs">
								<span v-if="d.stopped_reason">
									{{ limitLabel(d.stopped_reason) }}
									<span v-if="d.limit_value" class="text-gray-400">
										({{ d.reached_value }}/{{ d.limit_value }})
									</span>
								</span>
								<span v-else class="text-gray-400">—</span>
							</td>
							<td class="px-4 py-2 text-gray-600">
								{{ d.delegation_depth }} / {{ d.handoff_count }} / {{ d.attempt_count || 1 }}
							</td>
							<td class="px-4 py-2 text-gray-500 text-xs">{{ d.modified }}</td>
						</tr>
						<tr v-if="!delegations.length">
							<td colspan="7" class="px-4 py-6 text-center text-gray-500">
								{{ anyDelegationFilter ? "Nothing matches those filters." : "No delegations yet." }}
							</td>
						</tr>
					</tbody>
				</table>
				<div class="mt-3 bg-white rounded-lg px-6 py-4 border-t flex items-center justify-between text-sm">
					<div class="text-gray-600">
						Showing {{ delegations.length ? dStart + 1 : 0 }} to
						{{ dStart + delegations.length }} of {{ dTotal }}
					</div>
					<div class="flex items-center gap-2">
						<Button variant="outline" :disabled="dStart === 0" @click="prevDelegationPage">
							Previous
						</Button>
						<Button
							variant="outline"
							:disabled="dStart + pageLengthNum >= dTotal"
							@click="nextDelegationPage"
						>
							Next
						</Button>
					</div>
				</div>
			</div>
		</div>

		<!-- Task monitor -->
		<template v-else>
			<div class="bg-white px-6 py-3 border-b flex flex-wrap gap-4 items-center">
				<FormControl
					type="select"
					v-model="filters.direction"
					:options="directionOptions"
					class="w-44"
					@change="loadTasks(0)"
				/>
				<FormControl
					type="select"
					v-model="filters.state"
					:options="stateOptions"
					class="w-48"
					@change="loadTasks(0)"
				/>
				<FormControl
					type="select"
					v-model="filters.agent"
					:options="taskAgentOptions"
					class="w-56"
					@change="loadTasks(0)"
				/>
				<Button
					v-if="filters.direction || filters.state || filters.agent"
					variant="ghost"
					@click="resetFilters"
				>
					Clear filters
				</Button>
				<div class="ml-auto flex items-center gap-4">
					<span class="text-sm text-gray-600">{{ total }} tasks</span>
				<div class="flex items-center gap-2">
					<span class="text-sm text-gray-600">Page Size:</span>
					<FormControl
						type="select"
						v-model="pageLength"
						:options="pageSizeOptions"
						class="w-20"
						@change="changePageSize"
					/>
				</div>
				</div>
			</div>
			<div class="flex-1 overflow-auto px-6 py-4">
				<div v-if="loading.tasks" class="text-sm text-gray-500">Loading…</div>
				<table v-else class="w-full text-sm bg-white rounded-lg overflow-hidden">
					<thead class="bg-gray-100 text-left text-xs uppercase text-gray-500">
						<tr>
							<th class="px-4 py-2">Direction</th>
							<th class="px-4 py-2" title="The agent or caller that asked for this work">
								Delegated by
							</th>
							<th class="px-4 py-2" title="The agent doing the work">Handled by</th>
							<th class="px-4 py-2">State</th>
							<th class="px-4 py-2" title="Nesting depth / total handoffs in this chain">
								Depth / handoffs
							</th>
							<th class="px-4 py-2">Waiting on</th>
							<th class="px-4 py-2">Started</th>
						</tr>
					</thead>
					<tbody>
						<template v-for="t in a2aTasks" :key="t.name">
							<tr
								class="border-t cursor-pointer hover:bg-gray-50"
								@click="expandedTask = expandedTask === t.name ? '' : t.name"
							>
								<td class="px-4 py-2">
									<Badge :theme="directionTheme(t.direction)">{{ t.direction }}</Badge>
								</td>
								<td class="px-4 py-2 text-gray-600">{{ initiator(t) }}</td>
								<td class="px-4 py-2 text-gray-600">{{ t.agent_configuration || "—" }}</td>
								<td class="px-4 py-2">
									<Badge :theme="stateTheme(t.state)">{{ t.state }}</Badge>
									<div v-if="t.error_message" class="text-xs text-red-600 mt-0.5">
										{{ t.error_message }}
									</div>
								</td>
								<td class="px-4 py-2 text-gray-600">
									{{ t.delegation_depth }} / {{ t.handoff_count }}
								</td>
								<td class="px-4 py-2 text-gray-600 text-xs">
									<span v-if="t.pending_human_task">a person</span>
									<span v-else-if="t.next_poll_at && !isTerminal(t.state)">
										next check {{ t.next_poll_at }}
									</span>
									<span v-else class="text-gray-400">—</span>
								</td>
								<td class="px-4 py-2 text-gray-500 text-xs">{{ t.creation }}</td>
							</tr>
							<!-- The full story of one handoff. Click the row to open. -->
							<tr v-if="expandedTask === t.name" class="border-t bg-gray-50">
								<td colspan="7" class="px-6 py-4">
									<div class="grid gap-3 md:grid-cols-2 text-sm">
										<div>
											<div class="text-xs uppercase text-gray-400 mb-1">What was asked</div>
											<div class="text-gray-800 whitespace-pre-wrap">{{ taskBrief(t) || "—" }}</div>
										</div>
										<div>
											<div class="text-xs uppercase text-gray-400 mb-1">Answer</div>
											<div class="text-gray-800 whitespace-pre-wrap">
												{{ t.status_message || t.error_message || "no answer yet" }}
											</div>
										</div>
									</div>
									<div class="flex flex-wrap gap-x-6 gap-y-1 mt-4 text-xs text-gray-600">
										<span>
											Task:
											<a :href="`/app/a2a-task/${t.name}`" target="_blank" class="text-blue-600 hover:underline">{{ t.name }}</a>
										</span>
										<span v-if="t.instance">
											Doing the work:
											<router-link :to="`/processa/instances/${t.instance}`" class="text-blue-600 hover:underline">{{ t.instance }}</router-link>
										</span>
										<span v-if="t.caller_instance">
											Waiting for it:
											<router-link :to="`/processa/instances/${t.caller_instance}`" class="text-blue-600 hover:underline">{{ t.caller_instance }}</router-link>
										</span>
										<span v-if="t.task_execution_id">Chain: {{ t.task_execution_id }}</span>
										<span>Started: {{ t.creation }}</span>
										<span v-if="t.completed_at">Finished: {{ t.completed_at }}</span>
										<span v-if="t.deadline && !isTerminal(t.state)">Deadline: {{ t.deadline }}</span>
									</div>
								</td>
							</tr>
						</template>
						<tr v-if="!a2aTasks.length">
							<td colspan="7" class="px-4 py-6 text-center text-gray-500">
								No tasks yet.
							</td>
						</tr>
					</tbody>
				</table>
				<div class="mt-3 bg-white rounded-lg px-6 py-4 border-t flex items-center justify-between text-sm">
					<div class="text-gray-600">
						Showing {{ a2aTasks.length ? start + 1 : 0 }} to
						{{ start + a2aTasks.length }} of {{ total }}
					</div>
					<div class="flex items-center gap-2">
						<Button variant="outline" :disabled="start === 0" @click="prevTaskPage">
							Previous
						</Button>
						<Button
							variant="outline"
							:disabled="start + pageLengthNum >= total"
							@click="nextTaskPage"
						>
							Next
						</Button>
					</div>
				</div>
			</div>
		</template>

		<!-- One delegation, in full. Opened by clicking a row. -->
		<Dialog v-model="delegationOpen" :options="{ title: 'Delegation', size: '2xl' }">
			<template #body-content>
				<div v-if="loading.delegation" class="text-sm text-gray-500">Loading…</div>
				<div v-else-if="openDelegationRow" class="flex flex-col gap-5 text-sm">
					<!-- What happened, in one line, before any of the fields -->
					<div class="flex flex-wrap items-center gap-2">
						<Badge :theme="delegationTheme(openDelegationRow.status)">
							{{ openDelegationRow.status }}
						</Badge>
						<span class="text-gray-900 font-medium">
							{{ openDelegationRow.delegating_agent || "someone" }}
							→
							{{ openDelegationRow.worker_agent || "an agent" }}
						</span>
						<span class="text-gray-400 text-xs">{{ openDelegationRow.name }}</span>
					</div>

					<!-- A limit that stopped it is the most important thing on the screen -->
					<div
						v-if="openDelegationRow.stopped_reason"
						class="rounded-lg border border-orange-200 bg-orange-50 px-4 py-3"
					>
						<div class="font-medium text-orange-900">
							Stopped at a limit — {{ limitLabel(openDelegationRow.stopped_reason) }}
						</div>
						<div class="text-orange-800 mt-0.5">
							<span v-if="openDelegationRow.limit_value">
								Reached {{ openDelegationRow.reached_value }} against a limit of
								{{ openDelegationRow.limit_value }}.
							</span>
							The work is not finished.
						</div>
						<div v-if="openDelegationRow.notified_user" class="text-xs text-orange-700 mt-1">
							{{ openDelegationRow.notified_user }} was told
							<span v-if="openDelegationRow.notified_at">on {{ openDelegationRow.notified_at }}</span>.
						</div>
					</div>

					<div class="grid gap-4 md:grid-cols-2">
						<div>
							<div class="text-xs uppercase text-gray-400 mb-1">What it was for</div>
							<div v-if="openDelegationRow.reference_name" class="text-gray-800">
								<a
									:href="referenceUrl(openDelegationRow)"
									target="_blank"
									class="text-blue-600 hover:underline"
								>
									{{ openDelegationRow.reference_name }}
								</a>
								<span class="text-gray-500"> · {{ openDelegationRow.reference_doctype }}</span>
								<div v-if="openDelegationTitle" class="text-gray-600 mt-0.5">
									{{ openDelegationTitle }}
								</div>
							</div>
							<div v-else class="text-gray-400">
								Nothing linked — the delegating run had no context document.
							</div>
						</div>
						<div>
							<div class="text-xs uppercase text-gray-400 mb-1">The hand-off</div>
							<div v-if="openDelegationRow.a2a_task" class="text-gray-800">
								<a
									:href="`/app/a2a-task/${openDelegationRow.a2a_task}`"
									target="_blank"
									class="text-blue-600 hover:underline"
								>
									{{ openDelegationRow.a2a_task }}
								</a>
								<Badge
									v-if="openDelegationTask"
									:theme="stateTheme(openDelegationTask.state)"
									class="ml-2"
								>
									{{ openDelegationTask.state }}
								</Badge>
							</div>
							<div v-else class="text-gray-400">no task row</div>
						</div>
					</div>

					<div>
						<div class="text-xs uppercase text-gray-400 mb-1">What was asked</div>
						<div class="text-gray-800 whitespace-pre-wrap">
							{{ openDelegationRow.instruction || "—" }}
						</div>
					</div>

					<div>
						<div class="text-xs uppercase text-gray-400 mb-1">What came back</div>
						<div class="text-gray-800 whitespace-pre-wrap">
							{{ delegationAnswer() }}
						</div>
					</div>

					<div class="grid gap-4 md:grid-cols-3 text-xs">
						<div>
							<div class="uppercase text-gray-400 mb-1">Counters</div>
							<div class="text-gray-700">
								depth {{ openDelegationRow.delegation_depth }} ·
								hand-offs {{ openDelegationRow.handoff_count }} ·
								attempts {{ openDelegationRow.attempt_count || 1 }}
							</div>
						</div>
						<div>
							<div class="uppercase text-gray-400 mb-1">Timing</div>
							<div class="text-gray-700">
								<div>started {{ openDelegationRow.started_at || "—" }}</div>
								<div v-if="openDelegationRow.ended_at">ended {{ openDelegationRow.ended_at }}</div>
								<div v-if="openDelegationTask && openDelegationTask.deadline">
									deadline {{ openDelegationTask.deadline }}
								</div>
							</div>
						</div>
						<div>
							<div class="uppercase text-gray-400 mb-1">Instances</div>
							<div class="text-gray-700 flex flex-col">
								<router-link
									v-if="openDelegationRow.orchestrator_instance"
									:to="`/processa/instances/${openDelegationRow.orchestrator_instance}`"
									class="text-blue-600 hover:underline"
								>
									{{ openDelegationRow.orchestrator_instance }} (asked)
								</router-link>
								<router-link
									v-if="openDelegationRow.worker_instance"
									:to="`/processa/instances/${openDelegationRow.worker_instance}`"
									class="text-blue-600 hover:underline"
								>
									{{ openDelegationRow.worker_instance }} (doing)
								</router-link>
								<span
									v-if="!openDelegationRow.orchestrator_instance && !openDelegationRow.worker_instance"
									class="text-gray-400"
								>
									—
								</span>
							</div>
						</div>
					</div>
				</div>
			</template>
		</Dialog>

		<Dialog v-model="remoteFormOpen" :options="{ title: remoteForm.name ? 'Edit remote agent' : 'New remote agent' }">
			<template #body-content>
				<div class="flex flex-col gap-3">
					<FormControl
						label="Name"
						v-model="remoteForm.agent_name"
						:disabled="!!remoteForm.name"
						placeholder="Partner Support Agent"
					/>
					<FormControl
						label="Endpoint URL"
						v-model="remoteForm.endpoint_url"
						placeholder="https://partner.example.com/a2a"
						description="Where its A2A endpoint lives. Changing this later sends the entry back to Draft."
					/>
					<FormControl
						type="select"
						label="Auth scheme"
						v-model="remoteForm.auth_scheme"
						:options="authSchemes"
					/>
					<FormControl
						v-if="remoteForm.auth_scheme === 'API Key Header'"
						label="Auth header name"
						v-model="remoteForm.auth_header_name"
						placeholder="Authorization"
					/>
					<FormControl
						v-if="remoteForm.auth_scheme !== 'None'"
						type="password"
						label="Credential"
						v-model="remoteForm.credential"
						description="Stored encrypted and read only when a call is made."
					/>
					<div class="grid grid-cols-2 gap-3">
						<FormControl label="Request timeout (s)" v-model="remoteForm.request_timeout" placeholder="30" />
						<FormControl label="Task deadline (min)" v-model="remoteForm.default_task_timeout_minutes" placeholder="240" />
						<FormControl label="Poll base (s)" v-model="remoteForm.poll_base_interval" placeholder="60" />
						<FormControl label="Poll max (s)" v-model="remoteForm.poll_max_interval" placeholder="900" />
					</div>
					<FormControl
						type="checkbox"
						label="Allow internal hosts"
						v-model="remoteForm.allow_internal_hosts"
						description="Only for pointing at this site itself. Leave off for real partners."
					/>
					<ErrorMessage v-if="formError" :message="formError" />
					<p class="text-xs text-gray-500">
						Saved as Draft. Fetch its card and approve it before any process can use it.
					</p>
				</div>
			</template>
			<template #actions>
				<Button variant="solid" :loading="saving" @click="saveRemote">
					{{ remoteForm.name ? "Save" : "Create" }}
				</Button>
			</template>
		</Dialog>

		<Dialog v-model="clientFormOpen" :options="{ title: 'New client' }">
			<template #body-content>
				<div class="flex flex-col gap-3">
					<FormControl label="Name" v-model="clientForm.client_name" placeholder="Partner A" />
					<FormControl
						type="textarea"
						label="Description"
						v-model="clientForm.description"
						placeholder="Who this caller is, and why they have access."
					/>
					<div>
						<div class="text-xs text-gray-600 mb-1">May call these agents</div>
						<AgentPicker v-model="clientForm.allowed_agents" :agents="ourAgents" />
					</div>
					<ErrorMessage v-if="formError" :message="formError" />
					<p class="text-xs text-gray-500">
						Saved as Draft. Approving it creates its service user and issues the key.
					</p>
				</div>
			</template>
			<template #actions>
				<Button variant="solid" :loading="saving" @click="saveClient">Create</Button>
			</template>
		</Dialog>

		<Dialog v-model="clientAgentsOpen" :options="{ title: 'Which agents this client may call' }">
			<template #body-content>
				<p class="text-sm text-gray-600 mb-2">
					Takes effect immediately — the door reads this list on every call. Only exposed
					agents can be granted.
				</p>
				<AgentPicker v-model="agentsForm.allowed_agents" :agents="ourAgents" />
				<ErrorMessage v-if="formError" :message="formError" class="mt-2" />
			</template>
			<template #actions>
				<Button variant="solid" :loading="saving" @click="saveClientAgents">Save</Button>
			</template>
		</Dialog>

		<Dialog v-model="cardOpen" :options="{ title: 'Agent card', size: '2xl' }">
			<template #body-content>
				<div v-if="openCard">
					<p class="text-sm text-gray-600 mb-2">
						This is exactly what an unauthenticated fetch of the card URL returns. It is
						generated from the configuration each time, so it cannot fall out of date.
					</p>
					<div class="text-xs text-gray-500 mb-3 break-all">
						<div class="mb-1"><span class="text-gray-400">Card:</span> {{ openCard.card_url }}</div>
						<div><span class="text-gray-400">Tasks:</span> {{ openCard.rpc_url }}</div>
					</div>
					<pre class="bg-gray-100 rounded p-3 text-xs overflow-auto max-h-96">{{ JSON.stringify(openCard.card, null, 2) }}</pre>
				</div>
			</template>
		</Dialog>

		<Dialog v-model="credentialsOpen" :options="{ title: 'Client credentials' }">
			<template #body-content>
				<p class="text-sm text-gray-600 mb-3">
					Hand these to the caller out of band. The secret is shown because it is
					decrypted on request — it is never stored on the client record.
				</p>
				<div class="text-sm">
					<div class="mb-2">
						<span class="text-gray-500">API key</span>
						<code class="block bg-gray-100 rounded px-2 py-1 mt-0.5">{{ credentials.api_key }}</code>
					</div>
					<div>
						<span class="text-gray-500">API secret</span>
						<code class="block bg-gray-100 rounded px-2 py-1 mt-0.5">{{ credentials.api_secret }}</code>
					</div>
				</div>
			</template>
		</Dialog>
	</div>
</template>

<script setup>
// WI-001934: the A2A operation, in the SPA.
//
// Read-mostly. Approvals, card fetches and credential reads all call the
// modules that own those rules, so this screen cannot become a second
// implementation of them.
import { computed, onMounted, reactive, ref, watch } from "vue"
import { Badge, Button, Dialog, ErrorMessage, FormControl, frappeRequest } from "frappe-ui"
import AgentPicker from "@/components/a2a/AgentPicker.vue"

const API = "/api/method/one_bpmn.api.a2a_admin_api."
const TERMINAL = ["completed", "canceled", "failed", "rejected", "timed-out"]

const tab = ref("ours")
const can = ref({ administer: false, read: false })
const loading = reactive({
	ours: false,
	remotes: false,
	clients: false,
	tasks: false,
	delegations: false,
	delegation: false,
})
const error = ref("")

const ourAgents = ref([])
const remotes = ref([])
const clients = ref([])
const a2aTasks = ref([])
const total = ref(0)
const start = ref(0)
// One page size for both lists — it reads as a preference for the screen
// rather than a setting per tab, which is how the instance list treats it too.
const pageLength = ref(20)

// FormControl's select hands back a string, and `start + "20"` is "020".
const pageLengthNum = computed(() => Number(pageLength.value) || 20)

const pageSizeOptions = [
	{ label: "10", value: 10 },
	{ label: "20", value: 20 },
	{ label: "50", value: 50 },
	{ label: "100", value: 100 },
]

const filters = reactive({ direction: "", state: "", agent: "" })

// Delegations: the same hand-offs, listed by the work they were for.
const delegations = ref([])
const dTotal = ref(0)
const dStart = ref(0)
const dFilters = reactive({ a2a_task: "", reference_doctype: "", reference_name: "", status: "" })
const filterOptions = ref({ statuses: [], doctypes: [], workers: [], task_agents: [] })
const delegationOpen = ref(false)
const openDelegationRow = ref(null)
const openDelegationTask = ref(null)
const openDelegationTitle = ref("")
const cardOpen = ref(false)
const openCard = ref(null)
const copied = ref("")
const credentialsOpen = ref(false)
const credentials = ref({ api_key: "", api_secret: "" })

const tabs = computed(() => [
	{ key: "ours", label: "Our agents", count: ourAgents.value.length || null },
	{ key: "remotes", label: "Remote agents", count: remotes.value.length || null },
	{ key: "clients", label: "Clients", count: clients.value.length || null },
	{ key: "tasks", label: "Tasks", count: total.value || null },
	{ key: "delegations", label: "Delegations", count: dTotal.value || null },
])

// Internal — one of our agents handing work to another on this site — is the
// most common direction, so it has to be filterable like the other two.
const directionOptions = [
	{ label: "All directions", value: "" },
	{ label: "Internal (same site)", value: "Internal" },
	{ label: "Inbound", value: "Inbound" },
	{ label: "Outbound", value: "Outbound" },
]

const stateOptions = [
	{ label: "All states", value: "" },
	{ label: "submitted", value: "submitted" },
	{ label: "working", value: "working" },
	{ label: "input-required", value: "input-required" },
	{ label: "completed", value: "completed" },
	{ label: "failed", value: "failed" },
	{ label: "canceled", value: "canceled" },
	{ label: "timed-out", value: "timed-out" },
]

// Built from the rows that exist, not from the doctype's Select options: a
// status nothing has reached, or an agent nothing has been delegated to, is a
// dead entry in a dropdown.
const taskAgentOptions = computed(() => [
	{ label: "All agents", value: "" },
	...filterOptions.value.task_agents.map((a) => ({ label: a, value: a })),
])

const doctypeOptions = computed(() => [
	{ label: "All doctypes", value: "" },
	...filterOptions.value.doctypes.map((d) => ({ label: d, value: d })),
])

const delegationStatusOptions = computed(() => [
	{ label: "All statuses", value: "" },
	...filterOptions.value.statuses.map((s) => ({ label: s, value: s })),
])

const anyDelegationFilter = computed(() =>
	Boolean(
		dFilters.a2a_task || dFilters.reference_doctype || dFilters.reference_name || dFilters.status
	)
)

// The same words the escalation puts in front of a person, so the screen and
// the notification do not describe one limit two ways.
const LIMIT_LABELS = {
	max_recursion_depth: "nesting depth",
	max_task_handoffs: "hand-offs between agents",
	delegation_deadline_minutes: "time allowed",
	turn_cap: "tool-calling turns",
	max_delegation_retries: "retries",
}

function limitLabel(reason) {
	return LIMIT_LABELS[reason] || reason
}

function delegationTheme(status) {
	if (status === "Completed") return "green"
	if (status === "Failed") return "red"
	if (status === "Needs Review") return "orange"
	if (status === "In Progress") return "blue"
	return "gray" // Delegated — handed over, not started
}

function referenceUrl(row) {
	const slug = String(row.reference_doctype || "").toLowerCase().replace(/ /g, "-")
	return `/app/${slug}/${encodeURIComponent(row.reference_name)}`
}

function delegationAnswer() {
	const task = openDelegationTask.value
	const row = openDelegationRow.value
	return (
		task?.status_message ||
		row?.error_message ||
		task?.error_message ||
		"no answer recorded"
	)
}

function isTerminal(state) {
	return TERMINAL.includes(state)
}

function statusTheme(status) {
	if (status === "Approved") return "green"
	if (status === "Revoked") return "red"
	return "gray"
}

function stateTheme(state) {
	if (state === "completed") return "green"
	if (["failed", "timed-out", "rejected"].includes(state)) return "red"
	if (state === "input-required") return "orange"
	if (state === "canceled") return "gray"
	return "blue"
}

function directionTheme(direction) {
	if (direction === "Inbound") return "blue"
	if (direction === "Outbound") return "green"
	return "gray" // Internal — never crossed a trust boundary
}

const expandedTask = ref("")

function taskBrief(task) {
	// The instruction the caller sent, stored as JSON on the row.
	try {
		const payload = JSON.parse(task.request_payload || "{}")
		return payload.instruction || payload.text || ""
	} catch (e) {
		return task.request_payload || ""
	}
}

function initiator(task) {
	// Who asked for the work. An Internal hop has no client and no remote
	// agent — its initiator is the delegating agent, which is exactly the
	// case the old client-or-remote fallback rendered as a dash.
	return task.delegated_by || task.client || task.remote_agent || "—"
}


// ── Registering and editing (WI-001934) ─────────────────────────────────────
const authSchemes = [
	{ label: "None", value: "None" },
	{ label: "Bearer", value: "Bearer" },
	{ label: "API Key Header", value: "API Key Header" },
]
const saving = ref(false)
const formError = ref("")
const remoteFormOpen = ref(false)
const clientFormOpen = ref(false)
const clientAgentsOpen = ref(false)
const remoteForm = ref(blankRemote())
const clientForm = ref({ client_name: "", description: "", allowed_agents: [] })
const agentsForm = ref({ name: "", allowed_agents: [] })

function blankRemote() {
	return {
		name: "",
		agent_name: "",
		endpoint_url: "",
		auth_scheme: "None",
		auth_header_name: "Authorization",
		credential: "",
		allow_internal_hosts: false,
		request_timeout: "",
		default_task_timeout_minutes: "",
		poll_base_interval: "",
		poll_max_interval: "",
	}
}

function openRemoteForm(remote) {
	formError.value = ""
	remoteForm.value = remote
		? {
				...blankRemote(),
				name: remote.name,
				agent_name: remote.agent_name,
				endpoint_url: remote.endpoint_url,
				auth_scheme: remote.auth_scheme || "None",
				allow_internal_hosts: Boolean(remote.allow_internal_hosts),
				request_timeout: remote.request_timeout || "",
				default_task_timeout_minutes: remote.default_task_timeout_minutes || "",
				poll_base_interval: remote.poll_base_interval || "",
				poll_max_interval: remote.poll_max_interval || "",
			}
		: blankRemote()
	remoteFormOpen.value = true
}

async function saveRemote() {
	formError.value = ""
	saving.value = true
	const f = remoteForm.value
	const payload = {
		endpoint_url: f.endpoint_url,
		auth_scheme: f.auth_scheme,
		auth_header_name: f.auth_header_name,
		allow_internal_hosts: f.allow_internal_hosts ? 1 : 0,
		request_timeout: f.request_timeout || undefined,
		default_task_timeout_minutes: f.default_task_timeout_minutes || undefined,
		poll_base_interval: f.poll_base_interval || undefined,
		poll_max_interval: f.poll_max_interval || undefined,
	}
	// An empty credential on edit means "leave the stored one alone".
	if (f.credential) payload.credential = f.credential
	try {
		if (f.name) {
			await call("update_remote_agent", { name: f.name, ...payload })
		} else {
			await call("create_remote_agent", { agent_name: f.agent_name, ...payload })
		}
		remoteFormOpen.value = false
		await loadRemotes()
	} catch (e) {
		formError.value = e.message || String(e)
	} finally {
		saving.value = false
	}
}

function openClientForm() {
	formError.value = ""
	clientForm.value = { client_name: "", description: "", allowed_agents: [] }
	clientFormOpen.value = true
}

async function saveClient() {
	formError.value = ""
	saving.value = true
	try {
		await call("create_client", {
			client_name: clientForm.value.client_name,
			description: clientForm.value.description,
			allowed_agents: JSON.stringify(clientForm.value.allowed_agents),
		})
		clientFormOpen.value = false
		await loadClients()
	} catch (e) {
		formError.value = e.message || String(e)
	} finally {
		saving.value = false
	}
}

function openClientAgents(client) {
	formError.value = ""
	agentsForm.value = { name: client.name, allowed_agents: [...(client.allowed_agents || [])] }
	clientAgentsOpen.value = true
}

async function saveClientAgents() {
	formError.value = ""
	saving.value = true
	try {
		await call("set_client_agents", {
			name: agentsForm.value.name,
			allowed_agents: JSON.stringify(agentsForm.value.allowed_agents),
		})
		clientAgentsOpen.value = false
		await loadClients()
	} catch (e) {
		formError.value = e.message || String(e)
	} finally {
		saving.value = false
	}
}

async function call(method, params) {
	return await frappeRequest({ url: API + method, params })
}

async function loadOurAgents() {
	loading.ours = true
	try {
		ourAgents.value = (await call("list_agent_cards")) || []
	} catch (e) {
		error.value = e.message || String(e)
	} finally {
		loading.ours = false
	}
}

async function loadRemotes() {
	loading.remotes = true
	try {
		remotes.value = (await call("list_remote_agents")) || []
	} catch (e) {
		error.value = e.message || String(e)
	} finally {
		loading.remotes = false
	}
}

async function loadClients() {
	loading.clients = true
	try {
		clients.value = (await call("list_clients")) || []
	} catch (e) {
		error.value = e.message || String(e)
	} finally {
		loading.clients = false
	}
}

async function loadTasks(from = 0) {
	loading.tasks = true
	try {
		const r = await call("list_tasks", {
			direction: filters.direction || undefined,
			state: filters.state || undefined,
			start: Math.max(0, from),
			page_length: pageLengthNum.value,
		})
		a2aTasks.value = r.tasks || []
		total.value = r.total || 0
		start.value = r.start || 0
	} catch (e) {
		error.value = e.message || String(e)
	} finally {
		loading.tasks = false
	}
}

function changePageSize() {
	// Both lists go back to the first page: leaving the other tab on an offset
	// that was calculated for a different page size shows a page that no longer
	// starts where it says it does.
	start.value = 0
	dStart.value = 0
	if (tab.value === "delegations") loadDelegations(0)
	else loadTasks(0)
}

function prevTaskPage() {
	loadTasks(Math.max(0, start.value - pageLengthNum.value))
}

function nextTaskPage() {
	loadTasks(start.value + pageLengthNum.value)
}

function prevDelegationPage() {
	loadDelegations(Math.max(0, dStart.value - pageLengthNum.value))
}

function nextDelegationPage() {
	loadDelegations(dStart.value + pageLengthNum.value)
}

function resetFilters() {
	filters.direction = ""
	filters.state = ""
	filters.agent = ""
	loadTasks(0)
}

async function loadDelegations(from = 0) {
	loading.delegations = true
	try {
		const r = await call("list_delegations", {
			a2a_task: dFilters.a2a_task || undefined,
			reference_doctype: dFilters.reference_doctype || undefined,
			reference_name: dFilters.reference_name || undefined,
			status: dFilters.status || undefined,
			start: Math.max(0, from),
			page_length: pageLengthNum.value,
		})
		delegations.value = r.delegations || []
		dTotal.value = r.total || 0
		dStart.value = r.start || 0
	} catch (e) {
		error.value = e.message || String(e)
	} finally {
		loading.delegations = false
	}
}

// The two name filters match on a fragment, so they search as you type — but
// not once per keystroke. Driven by a watcher rather than @input because
// FormControl is a wrapper, and whether a native listener reaches the input
// inside it is its business, not this screen's.
let delegationTimer = null
watch(
	() => [dFilters.a2a_task, dFilters.reference_name],
	() => {
		clearTimeout(delegationTimer)
		delegationTimer = setTimeout(() => loadDelegations(0), 300)
	}
)

function resetDelegationFilters() {
	dFilters.a2a_task = ""
	dFilters.reference_doctype = ""
	dFilters.reference_name = ""
	dFilters.status = ""
	loadDelegations(0)
}

async function openDelegation(row) {
	// Show what the list already has, then fill in the rest — the modal opens
	// immediately rather than after a round trip.
	openDelegationRow.value = row
	openDelegationTask.value = null
	openDelegationTitle.value = ""
	delegationOpen.value = true
	loading.delegation = true
	try {
		const r = await call("delegation_detail", { name: row.name })
		openDelegationRow.value = r.delegation || row
		openDelegationTask.value = r.task || null
		openDelegationTitle.value = r.reference_title || ""
	} catch (e) {
		error.value = e.message || String(e)
	} finally {
		loading.delegation = false
	}
}

async function loadFilterOptions() {
	try {
		filterOptions.value = await call("delegation_filter_options")
	} catch (e) {
		// A screen that cannot build its dropdowns still lists rows.
		filterOptions.value = { statuses: [], doctypes: [], workers: [], task_agents: [] }
	}
}

async function fetchCard(remote) {
	error.value = ""
	try {
		await call("fetch_remote_card", { name: remote.name })
		await loadRemotes()
	} catch (e) {
		error.value = e.message || String(e)
	}
}

async function setRemote(remote, status) {
	error.value = ""
	try {
		await call("set_remote_approval", { name: remote.name, approval_status: status })
		await loadRemotes()
	} catch (e) {
		error.value = e.message || String(e)
	}
}

async function setClient(client, status) {
	error.value = ""
	try {
		await call("set_client_approval", { name: client.name, approval_status: status })
		await loadClients()
	} catch (e) {
		error.value = e.message || String(e)
	}
}

function showCard(agent) {
	openCard.value = agent
	cardOpen.value = true
}

async function copyCardUrl(agent) {
	try {
		await navigator.clipboard.writeText(agent.card_url)
		copied.value = agent.agent_id
		setTimeout(() => (copied.value = ""), 1500)
	} catch (e) {
		error.value = "Could not copy the link — select it from the card view instead."
	}
}

async function showCredentials(client) {
	error.value = ""
	try {
		credentials.value = await call("get_client_credentials", { name: client.name })
		credentialsOpen.value = true
	} catch (e) {
		error.value = e.message || String(e)
	}
}

onMounted(async () => {
	can.value = (await call("get_permissions")) || can.value
	if (!can.value.administer) return
	await Promise.all([
		loadOurAgents(),
		loadRemotes(),
		loadClients(),
		loadTasks(0),
		loadDelegations(0),
		loadFilterOptions(),
	])
})
</script>
