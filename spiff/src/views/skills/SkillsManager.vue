<template>
	<div class="h-full flex flex-col bg-white">
		<!-- Header -->
		<div class="flex-none border-b px-6 py-4 bg-white flex justify-between items-center shadow-sm z-10">
			<div>
				<h1 class="text-2xl font-bold text-gray-900 tracking-tight">AI Skills Library</h1>
				<p class="text-sm text-gray-500 mt-1">Manage reusable AI operational knowledge and procedures.</p>
			</div>
			<div class="flex gap-3">
				
				<button 
					@click="createNewSkill"
					class="inline-flex items-center px-4 py-2 border border-gray-300 shadow-sm text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 transition-colors"
				>
					<Icon icon="lucide:plus" class="w-4 h-4 mr-2" />
					New Skill
				</button>
<button 
					@click="showHarvestModal = true"
					class="inline-flex items-center px-4 py-2 border border-gray-300 shadow-sm text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 transition-colors"
				>
					<Icon icon="lucide:bot" class="w-4 h-4 mr-2" />
					Harvest from Run
				</button>
				<button 
					@click="refreshSkills" 
					class="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-gray-900 hover:bg-gray-800 shadow-sm transition-colors"
				>
					<Icon icon="lucide:refresh-cw" class="w-4 h-4 mr-2" :class="{ 'animate-spin': loading }" />
					Refresh
				</button>
			</div>
		</div>

		<!-- Main Content -->
		<div class="flex-1 flex overflow-hidden">
			<!-- Left Sidebar: Skill List -->
			<div class="w-80 flex-none border-r bg-gray-50/50 flex flex-col overflow-hidden">
				<div class="p-4 border-b bg-white">
					<div class="relative rounded-md shadow-sm">
						<div class="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
							<Icon icon="lucide:search" class="h-4 w-4 text-gray-400" />
						</div>
						<input 
							type="text" 
							v-model="searchQuery"
							class="focus:ring-gray-500 focus:border-gray-500 block w-full pl-10 sm:text-sm border-gray-300 rounded-md"
							placeholder="Search skills..."
						>
					</div>
				</div>
				
				<div class="flex-1 overflow-y-auto p-2 space-y-1">
					<div v-if="loading && skills.length === 0" class="p-4 text-center text-sm text-gray-500">
						Loading skills...
					</div>
					<div v-else-if="filteredSkills.length === 0" class="p-4 text-center text-sm text-gray-500">
						No skills found.
					</div>
					<div v-else>
						<button 
							v-for="skill in filteredSkills" 
							:key="skill.name"
							@click="selectSkill(skill)"
							class="w-full text-left px-4 py-3 rounded-lg border transition-all duration-150"
							:class="[
								selectedSkill?.name === skill.name 
									? 'bg-white border-gray-300 shadow-sm ring-1 ring-gray-900' 
									: 'bg-transparent border-transparent hover:bg-gray-100'
							]"
						>
							<div class="flex justify-between items-start mb-1">
								<span class="font-medium text-sm text-gray-900 truncate pr-2">{{ skill.skill_name || skill.name }}</span>
								<span 
									class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
									:class="{
										'bg-green-100 text-green-800': skill.tier === 'Action-Allowed',
										'bg-blue-100 text-blue-800': skill.tier === 'Read-Only',
										'bg-gray-100 text-gray-800': skill.tier === 'Draft-Only',
										'bg-purple-100 text-purple-800': skill.status === 'Active' && !skill.tier,
										'bg-yellow-100 text-yellow-800': skill.status === 'Draft'
									}"
								>
									{{ skill.tier || skill.status }}
								</span>
							</div>
							<p class="text-xs text-gray-500 line-clamp-2">{{ skill.description || 'No description provided.' }}</p>
						</button>
					</div>
				</div>
			</div>

			<!-- Right Area: Detail View -->
			<div class="flex-1 flex flex-col bg-white overflow-hidden relative">
				<div v-if="!selectedSkill" class="absolute inset-0 flex items-center justify-center text-gray-400">
					<div class="text-center">
						<Icon icon="lucide:brain-circuit" class="w-12 h-12 mx-auto mb-3 opacity-50" />
						<p>Select a skill from the sidebar to view details</p>
					</div>
				</div>
				
				<template v-else>
					<!-- Tab Navigation -->
					<div class="flex-none border-b px-6 bg-gray-50">
						<nav class="-mb-px flex space-x-8">
							<button 
								v-for="tab in ['Editor', 'Settings', 'Telemetry']" 
								:key="tab"
								@click="activeTab = tab"
								class="whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm transition-colors"
								:class="[
									activeTab === tab 
										? 'border-gray-900 text-gray-900' 
										: 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
								]"
							>
								{{ tab }}
							</button>
						</nav>
					</div>

					<!-- Settings Tab -->
					<div v-if="activeTab === 'Settings'" class="flex-1 flex flex-col overflow-y-auto bg-gray-50 p-6">
						<div class="bg-white shadow rounded-lg border">
							<div class="px-4 py-5 sm:px-6 border-b flex justify-between items-center">
								<h3 class="text-lg leading-6 font-medium text-gray-900">Skill Settings</h3>
								<button 
									@click="saveSkillSettings" 
									:disabled="saving"
									class="px-3 py-1.5 text-sm font-medium text-white bg-gray-900 rounded-md shadow-sm hover:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-gray-900 disabled:opacity-50 transition-colors flex items-center gap-2"
								>
									<Icon v-if="saving" icon="lucide:loader-2" class="w-4 h-4 animate-spin" />
									<Icon v-else icon="lucide:save" class="w-4 h-4" />
									Save Changes
								</button>
							</div>
							<div class="px-4 py-5 sm:p-6 space-y-6">
                                <div>
                                    <label class="block text-sm font-medium text-gray-700">Description</label>
                                    <textarea v-model="selectedSkill.description" rows="3" class="mt-1 shadow-sm focus:ring-gray-500 focus:border-gray-500 block w-full sm:text-sm border-gray-300 rounded-md"></textarea>
                                </div>

                                <div class="border-t pt-6">
                                    <label class="block text-sm font-medium text-gray-700">Body (Markdown)</label>
                                    <textarea v-model="editedBody" rows="8" class="mt-1 shadow-sm focus:ring-gray-500 focus:border-gray-500 block w-full sm:text-sm border-gray-300 rounded-md font-mono" placeholder="Markdown instructions for the agent..."></textarea>
                                </div>

                                <div class="grid grid-cols-1 gap-y-6 gap-x-4 sm:grid-cols-6">
                                    <div class="sm:col-span-6 border-t pt-6">
                                        <h4 class="text-sm font-medium text-gray-900 mb-4">Allowed Tools</h4>
                                        <div class="flex gap-4">
                                            <div class="flex-1">
                                                <div class="flex flex-wrap gap-2 mb-4">
                                                    <span v-for="(t, idx) in selectedSkill.allowed_tools || []" :key="idx" class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800">
                                                        {{ t.tool }}
                                                        <button type="button" @click="removeTool(idx)" class="ml-1.5 flex-shrink-0 inline-flex text-gray-400 hover:bg-gray-200 hover:text-gray-500 rounded-full focus:outline-none focus:bg-gray-500 focus:text-white">
                                                            <span class="sr-only">Remove tool</span>
                                                            <svg class="h-2 w-2" stroke="currentColor" fill="none" viewBox="0 0 8 8">
                                                                <path stroke-linecap="round" stroke-width="1.5" d="M1 1l6 6m0-6L1 7" />
                                                            </svg>
                                                        </button>
                                                    </span>
                                                    <span v-if="!(selectedSkill.allowed_tools || []).length" class="text-sm text-gray-500">No tools allowed</span>
                                                </div>
                                            </div>
                                            <div class="w-64">
                                                <input type="text" v-model="toolSearch" placeholder="Search to add tool..." class="shadow-sm focus:ring-gray-500 focus:border-gray-500 block w-full sm:text-sm border-gray-300 rounded-md mb-2">
                                                <div class="max-h-40 overflow-y-auto border rounded-md">
                                                    <button v-for="tool in filteredTools" :key="tool.name" @click="addTool(tool.name)" class="w-full text-left px-3 py-2 text-sm hover:bg-gray-50 truncate" :title="tool.name">
                                                        + {{ tool.name }}
                                                    </button>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    
                                    <div class="sm:col-span-6 border-t pt-6">
                                        <div class="flex justify-between items-center mb-4">
                                            <h4 class="text-sm font-medium text-gray-900">Resources</h4>
                                            <button @click="addResource" type="button" class="inline-flex items-center px-3 py-1.5 border border-gray-300 shadow-sm text-xs font-medium rounded text-gray-700 bg-white hover:bg-gray-50">
                                                Add Resource
                                            </button>
                                        </div>
                                        
                                        <div v-for="(r, idx) in selectedSkill.resources || []" :key="idx" class="bg-gray-50 p-4 rounded-lg mb-4 border">
                                            <div class="flex justify-between items-start mb-4">
                                                <div class="flex-1 grid grid-cols-2 gap-4">
                                                    <div>
                                                        <label class="block text-xs font-medium text-gray-700">Type</label>
                                                        <select v-model="r.resource_type" class="mt-1 block w-full pl-3 pr-10 py-1.5 text-base border-gray-300 focus:outline-none focus:ring-gray-500 focus:border-gray-500 sm:text-sm rounded-md">
                                                            <option value="Script">Script</option>
                                                            <option value="Reference">Reference</option>
                                                            <option value="Asset">Asset</option>
                                                            <option value="Template">Template</option>
                                                        </select>
                                                    </div>
                                                    <div>
                                                        <label class="block text-xs font-medium text-gray-700">Name</label>
                                                        <input type="text" v-model="r.resource_name" class="mt-1 shadow-sm focus:ring-gray-500 focus:border-gray-500 block w-full sm:text-sm border-gray-300 rounded-md">
                                                    </div>
                                                </div>
                                                <button @click="removeResource(idx)" type="button" class="ml-4 text-gray-400 hover:text-red-500">
                                                    <Icon icon="lucide:trash-2" class="w-4 h-4" />
                                                </button>
                                            </div>
                                            <div>
                                                <label class="block text-xs font-medium text-gray-700">Value</label>
                                                <textarea v-model="r.resource_value" rows="2" class="mt-1 shadow-sm focus:ring-gray-500 focus:border-gray-500 block w-full sm:text-sm border-gray-300 rounded-md font-mono"></textarea>
                                            </div>
                                        </div>
                                        <div v-if="!(selectedSkill.resources || []).length" class="text-sm text-gray-500 text-center py-4 bg-gray-50 rounded-lg border border-dashed">
                                            No resources attached
                                        </div>
                                    </div>

                                </div>
                                <div class="grid grid-cols-1 gap-y-6 gap-x-4 sm:grid-cols-6 border-t pt-6">
                                    <div class="sm:col-span-3">
                                        <label class="block text-sm font-medium text-gray-700">Tier</label>
                                        <select v-model="selectedSkill.tier" class="mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-gray-500 focus:border-gray-500 sm:text-sm rounded-md">
                                            <option value="Read-Only">Read-Only</option>
                                            <option value="Draft-Only">Draft-Only</option>
                                            <option value="Action-Allowed">Action-Allowed</option>
                                        </select>
                                    </div>
                                    <div class="sm:col-span-3">
                                        <label class="block text-sm font-medium text-gray-700">Status</label>
                                        <select v-model="selectedSkill.status" class="mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-gray-500 focus:border-gray-500 sm:text-sm rounded-md">
                                            <option value="Draft">Draft</option>
                                            <option value="Active">Active</option>
                                            <option value="Deprecated">Deprecated</option>
                                        </select>
                                    </div>
                                </div>
							</div>
						</div>
					</div>

					<!-- Editor Tab -->
					<div v-if="activeTab === 'Editor'" class="flex-1 flex flex-col overflow-hidden">
						<div class="p-4 border-b flex items-center justify-between bg-white flex-none">
							<h3 class="font-medium text-gray-900">Skill Body (Markdown)</h3>
							<button 
								@click="saveSkillBody" 
								:disabled="saving"
								class="px-3 py-1.5 text-sm font-medium text-white bg-gray-900 rounded-md shadow-sm hover:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-gray-900 disabled:opacity-50 transition-colors flex items-center gap-2"
							>
								<Icon v-if="saving" icon="lucide:loader-2" class="w-4 h-4 animate-spin" />
								<Icon v-else icon="lucide:save" class="w-4 h-4" />
								Save Changes
							</button>
						</div>
						<div class="flex-1 p-0 overflow-hidden relative bg-gray-50">
							<textarea 
								v-model="editedBody" 
								class="absolute inset-0 w-full h-full p-4 font-mono text-sm resize-none focus:ring-0 focus:outline-none border-none bg-transparent"
								placeholder="Markdown instructions for the agent..."
							></textarea>
						</div>
					</div>

					<!-- Telemetry Tab -->
					<div v-if="activeTab === 'Telemetry'" class="flex-1 overflow-y-auto bg-gray-50 p-6">
						<div class="bg-white shadow rounded-lg border">
							<div class="px-4 py-5 sm:px-6 border-b flex justify-between items-center">
								<h3 class="text-lg leading-6 font-medium text-gray-900">Activation Logs</h3>
								<button @click="loadTelemetry" class="text-sm text-blue-600 hover:text-blue-800 flex items-center gap-1">
									<Icon icon="lucide:refresh-cw" class="w-4 h-4" :class="{ 'animate-spin': loadingTelemetry }" />
									Refresh
								</button>
							</div>
							<div class="border-t border-gray-200">
								<div v-if="loadingTelemetry" class="p-6 text-center text-sm text-gray-500">
									Loading telemetry...
								</div>
								<div v-else-if="telemetry.length === 0" class="p-6 text-center text-sm text-gray-500">
									No activation logs found for this skill.
								</div>
								<table v-else class="min-w-full divide-y divide-gray-200">
									<thead class="bg-gray-50">
										<tr>
											<th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Date</th>
											<th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Agent Run</th>
											<th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Conversation ID</th>
										</tr>
									</thead>
									<tbody class="bg-white divide-y divide-gray-200">
										<tr v-for="log in telemetry" :key="log.name" class="hover:bg-gray-50">
											<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
												{{ new Date(log.loaded_at).toLocaleString() }}
											</td>
											<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 font-mono">
												{{ log.agent_run || '-' }}
											</td>
											<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 font-mono">
												{{ log.conversation || '-' }}
											</td>
										</tr>
									</tbody>
								</table>
							</div>
						</div>
					</div>
				</template>
			</div>
		</div>

		<!-- Harvest Modal -->
		<div v-if="showHarvestModal" class="fixed inset-0 z-50 overflow-y-auto" aria-labelledby="modal-title" role="dialog" aria-modal="true">
			<div class="flex items-end justify-center min-h-screen pt-4 px-4 pb-20 text-center sm:block sm:p-0">
				<div class="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity" aria-hidden="true" @click="showHarvestModal = false"></div>
				<span class="hidden sm:inline-block sm:align-middle sm:h-screen" aria-hidden="true">&#8203;</span>
				<div class="inline-block align-bottom bg-white rounded-lg text-left overflow-hidden shadow-xl transform transition-all sm:my-8 sm:align-middle sm:max-w-lg sm:w-full">
					<div class="bg-white px-4 pt-5 pb-4 sm:p-6 sm:pb-4">
						<div class="sm:flex sm:items-start">
							<div class="mx-auto flex-shrink-0 flex items-center justify-center h-12 w-12 rounded-full bg-blue-100 sm:mx-0 sm:h-10 sm:w-10">
								<Icon icon="lucide:bot" class="h-6 w-6 text-blue-600" />
							</div>
							<div class="mt-3 text-center sm:mt-0 sm:ml-4 sm:text-left w-full">
								<h3 class="text-lg leading-6 font-medium text-gray-900" id="modal-title">Harvest Skill from Run</h3>
								<div class="mt-2">
									<p class="text-sm text-gray-500 mb-4">
										Enter the name of a successful AI Agent Run. A background LLM will analyze the transcript and draft a generalized skill.
									</p>
									<input 
										type="text" 
										v-model="harvestRunName"
										class="shadow-sm focus:ring-gray-500 focus:border-gray-500 block w-full sm:text-sm border-gray-300 rounded-md"
										placeholder="e.g. RUN-2026-0001"
									>
								</div>
							</div>
						</div>
					</div>
					<div class="bg-gray-50 px-4 py-3 sm:px-6 sm:flex sm:flex-row-reverse">
						<button 
							type="button" 
							class="w-full inline-flex justify-center rounded-md border border-transparent shadow-sm px-4 py-2 bg-gray-900 text-base font-medium text-white hover:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-gray-900 sm:ml-3 sm:w-auto sm:text-sm"
							@click="harvestSkill"
							:disabled="harvesting || !harvestRunName"
						>
							<Icon v-if="harvesting" icon="lucide:loader-2" class="w-4 h-4 mr-2 animate-spin" />
							{{ harvesting ? 'Harvesting...' : 'Harvest' }}
						</button>
						<button 
							type="button" 
							class="mt-3 w-full inline-flex justify-center rounded-md border border-gray-300 shadow-sm px-4 py-2 bg-white text-base font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-gray-500 sm:mt-0 sm:ml-3 sm:w-auto sm:text-sm"
							@click="showHarvestModal = false"
						>
							Cancel
						</button>
					</div>
				</div>
			</div>
		</div>

		<!-- Create Modal -->
		<div v-if="showCreateModal" class="fixed inset-0 z-50 overflow-y-auto" aria-labelledby="modal-title" role="dialog" aria-modal="true">
			<div class="flex items-end justify-center min-h-screen pt-4 px-4 pb-20 text-center sm:block sm:p-0">
				<div class="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity" aria-hidden="true" @click="showCreateModal = false"></div>
				<span class="hidden sm:inline-block sm:align-middle sm:h-screen" aria-hidden="true">&#8203;</span>
				<div class="inline-block align-bottom bg-white rounded-lg text-left overflow-hidden shadow-xl transform transition-all sm:my-8 sm:align-middle sm:max-w-lg sm:w-full">
					<div class="bg-white px-4 pt-5 pb-4 sm:p-6 sm:pb-4">
						<div class="sm:flex sm:items-start">
							<div class="mx-auto flex-shrink-0 flex items-center justify-center h-12 w-12 rounded-full bg-blue-100 sm:mx-0 sm:h-10 sm:w-10">
								<Icon icon="lucide:plus" class="h-6 w-6 text-blue-600" />
							</div>
							<div class="mt-3 text-center sm:mt-0 sm:ml-4 sm:text-left w-full">
								<h3 class="text-lg leading-6 font-medium text-gray-900" id="modal-title">Create New Skill</h3>
								<div class="mt-4 space-y-4">
                                    <div>
                                        <label class="block text-sm font-medium text-gray-700">Skill Name <span class="text-red-500">*</span></label>
                                        <input type="text" v-model="newSkillForm.skill_name" class="mt-1 shadow-sm focus:ring-gray-500 focus:border-gray-500 block w-full sm:text-sm border-gray-300 rounded-md" placeholder="e.g. Find Employee">
                                    </div>
                                    <div>
                                        <label class="block text-sm font-medium text-gray-700">Description</label>
                                        <textarea v-model="newSkillForm.description" rows="2" class="mt-1 shadow-sm focus:ring-gray-500 focus:border-gray-500 block w-full sm:text-sm border-gray-300 rounded-md" placeholder="Brief description of what the skill does"></textarea>
                                    </div>
                                    <div>
                                        <label class="block text-sm font-medium text-gray-700">Tier</label>
                                        <select v-model="newSkillForm.tier" class="mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-gray-500 focus:border-gray-500 sm:text-sm rounded-md">
                                            <option value="Read-Only">Read-Only</option>
                                            <option value="Draft-Only">Draft-Only</option>
                                            <option value="Action-Allowed">Action-Allowed</option>
                                        </select>
                                    </div>
                                    <div>
                                        <label class="block text-sm font-medium text-gray-700">Status</label>
                                        <select v-model="newSkillForm.status" class="mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-gray-500 focus:border-gray-500 sm:text-sm rounded-md">
                                            <option value="Draft">Draft</option>
                                            <option value="Active">Active</option>
                                            <option value="Deprecated">Deprecated</option>
                                        </select>
                                    </div>
                                    <div>
                                        <label class="block text-sm font-medium text-gray-700">Body (Markdown)</label>
                                        <textarea v-model="newSkillForm.body" rows="6" class="mt-1 shadow-sm focus:ring-gray-500 focus:border-gray-500 block w-full sm:text-sm border-gray-300 rounded-md font-mono" placeholder="Markdown instructions for the agent..."></textarea>
                                    </div>
								</div>
							</div>
						</div>
					</div>
					<div class="bg-gray-50 px-4 py-3 sm:px-6 sm:flex sm:flex-row-reverse">
						<button
							type="button"
							class="w-full inline-flex justify-center rounded-md border border-transparent shadow-sm px-4 py-2 bg-gray-900 text-base font-medium text-white hover:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-gray-900 sm:ml-3 sm:w-auto sm:text-sm"
							@click="submitNewSkill"
							:disabled="creating || !newSkillForm.skill_name"
						>
							<Icon v-if="creating" icon="lucide:loader-2" class="w-4 h-4 mr-2 animate-spin" />
							{{ creating ? 'Creating...' : 'Create Skill' }}
						</button>
						<button 
							type="button" 
							class="mt-3 w-full inline-flex justify-center rounded-md border border-gray-300 shadow-sm px-4 py-2 bg-white text-base font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-gray-500 sm:mt-0 sm:ml-3 sm:w-auto sm:text-sm"
							@click="showCreateModal = false"
						>
							Cancel
						</button>
					</div>
				</div>
			</div>
		</div>

	</div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { Icon } from '@iconify/vue'
import { call } from 'frappe-ui'
const allTools = ref([])
const toolSearch = ref('')

const filteredTools = computed(() => {
    if (!toolSearch.value) return allTools.value
    const query = toolSearch.value.toLowerCase()
    return allTools.value.filter(t => t.name.toLowerCase().includes(query))
})


const showCreateModal = ref(false)
const newSkillForm = ref({
    skill_name: '',
    description: '',
    tier: 'Read-Only',
    status: 'Draft',
    owner_team: '',
    body: ''
})
const creating = ref(false)

function createNewSkill() {
	showCreateModal.value = true
}

async function submitNewSkill() {
    if (!newSkillForm.value.skill_name) {
        alert("Skill name is required");
        return;
    }
    creating.value = true;
    try {
        const res = await call(
            'frappe.client.insert',
            {
                doc: {
                    doctype: 'AI Skill',
                    skill_name: newSkillForm.value.skill_name,
                    description: newSkillForm.value.description,
                    tier: newSkillForm.value.tier,
                    status: newSkillForm.value.status || 'Draft',
                    owner_team: newSkillForm.value.owner_team,
                    body: newSkillForm.value.body || ''
                }
            }
        );
        if (res) {
            showCreateModal.value = false;
            newSkillForm.value = {
                skill_name: '',
                description: '',
                tier: 'Read-Only',
                status: 'Draft',
                owner_team: '',
                body: ''
            };
            await refreshSkills();
            selectSkill(res);
        }
    } catch (err) {
        console.error("Failed to create skill", err);
        alert("Failed to create skill");
    } finally {
        creating.value = false;
    }
}



const skills = ref([])
const loading = ref(false)
const searchQuery = ref('')
const selectedSkill = ref(null)
const activeTab = ref('Editor')
const editedBody = ref('')
const saving = ref(false)

const telemetry = ref([])
const loadingTelemetry = ref(false)

const showHarvestModal = ref(false)
const harvestRunName = ref('')
const harvesting = ref(false)

const filteredSkills = computed(() => {
	if (!searchQuery.value) return skills.value
	const query = searchQuery.value.toLowerCase()
	return skills.value.filter(s => 
		(s.skill_name || s.name).toLowerCase().includes(query) || 
		(s.description || '').toLowerCase().includes(query)
	)
})

const refreshSkills = async () => {
	loading.value = true
	try {
		const res = await call(
			'one_bpmn.api.skills_api.get_skills_library'
		)
		if (res) {
			skills.value = res
		}
	} catch (err) {
		console.error("Failed to load skills:", err)
		alert('Failed to load skills library')
	} finally {
		loading.value = false
	}
}

const selectSkill = async (skill) => {
	selectedSkill.value = skill
	activeTab.value = 'Editor'
	
	// Fetch the full document to get the body
	try {
		const res = await call(
			'frappe.client.get',
			{
				doctype: 'AI Skill',
				name: skill.name
			}
		)
		if (res) {
			editedBody.value = res.body || ''
            Object.assign(selectedSkill.value, res)
		}
	} catch (err) {
		console.error("Failed to fetch skill details", err)
	}
}


const addResource = () => {
    if (!selectedSkill.value.resources) selectedSkill.value.resources = []
    selectedSkill.value.resources.push({
        resource_type: 'Reference',
        resource_name: '',
        resource_value: ''
    })
}

const removeResource = (idx) => {
    selectedSkill.value.resources.splice(idx, 1)
}

const addTool = (toolName) => {
    if (!selectedSkill.value.allowed_tools) selectedSkill.value.allowed_tools = []
    if (!selectedSkill.value.allowed_tools.find(t => t.tool === toolName)) {
        selectedSkill.value.allowed_tools.push({ tool: toolName })
    }
}

const removeTool = (idx) => {
    selectedSkill.value.allowed_tools.splice(idx, 1)
}
const saveSkillSettings = async () => {
	if (!selectedSkill.value) return
	saving.value = true
	try {
		await call(
			'frappe.client.set_value',
			{
				doctype: 'AI Skill',
				name: selectedSkill.value.name,
                fieldname: {
                    description: selectedSkill.value.description,
                    body: editedBody.value,
                    tier: selectedSkill.value.tier,
                    status: selectedSkill.value.status,
                    owner_team: selectedSkill.value.owner_team,
                    resources: selectedSkill.value.resources || [],
                    allowed_tools: selectedSkill.value.allowed_tools || []
                }
			}
		)
        await refreshSkills()
		alert('Skill settings saved successfully')
	} catch (err) {
		console.error("Failed to save skill settings", err)
		alert('Failed to save skill settings')
	} finally {
		saving.value = false
	}
}

const saveSkillBody = async () => {
	if (!selectedSkill.value) return
	saving.value = true
	try {
		await call(
			'one_bpmn.api.skills_api.update_skill_body',
			{
				skill_name: selectedSkill.value.name,
				new_body: editedBody.value
			}
		)
		alert('Skill body saved successfully')
	} catch (err) {
		console.error("Failed to save skill body", err)
		alert('Failed to save skill body')
	} finally {
		saving.value = false
	}
}

const loadTelemetry = async () => {
	if (!selectedSkill.value) return
	loadingTelemetry.value = true
	try {
		const res = await call(
			'one_bpmn.api.skills_api.get_skill_telemetry',
			{
				skill_name: selectedSkill.value.name
			}
		)
		if (res) {
			telemetry.value = res
		}
	} catch (err) {
		console.error("Failed to load telemetry", err)
	} finally {
		loadingTelemetry.value = false
	}
}

const harvestSkill = async () => {
	if (!harvestRunName.value) return
	harvesting.value = true
	try {
		const res = await call(
			'one_bpmn.api.skill_creator.harvest_skill_from_run',
			{
				run_name: harvestRunName.value
			}
		)
		if (res) {
			alert(`Successfully harvested as ${res}`)
			showHarvestModal.value = false
			harvestRunName.value = ''
			await refreshSkills()
		}
	} catch (err) {
		console.error("Failed to harvest skill", err)
		alert(err.message || 'Failed to harvest skill')
	} finally {
		harvesting.value = false
	}
}

// Watch tab change to load telemetry lazily
watch(activeTab, (newTab) => {
	if (newTab === 'Telemetry' && telemetry.value.length === 0) {
		loadTelemetry()
	}
})

// Also reload telemetry if selected skill changes while on Telemetry tab
watch(selectedSkill, (newSkill, oldSkill) => {
	if (newSkill && oldSkill && newSkill.name !== oldSkill.name) {
		telemetry.value = []
		if (activeTab.value === 'Telemetry') {
			loadTelemetry()
		}
	}
})

onMounted(() => {
	
    call('frappe.client.get_list', {
        doctype: 'AI Agent Tool',
        limit_page_length: 0
    }).then(res => {
        if (res) allTools.value = res
    }).catch(console.error)
refreshSkills()
})
</script>
