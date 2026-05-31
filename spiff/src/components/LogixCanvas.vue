<template>
	<div class="lc-root">

		<!-- ── LEFT: Chat Panel ──────────────────────────────────────── -->
		<div class="lc-chat-panel">

			<!-- Chat header -->
			<div class="lc-chat-header">
				<div class="lc-chat-header-left">
					<span class="lc-header-avatar">
						<svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
							<path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
						</svg>
					</span>
					<span class="lc-header-title">Logix Assistant</span>
					<span v-if="elementLabel" class="lc-header-chip" :title="elementLabel">{{ elementLabel }}</span>
				</div>
				<button class="lc-header-btn" @click="resetChat" title="New conversation">
					<svg viewBox="0 0 24 24" fill="currentColor" width="15" height="15">
						<path d="M17.65 6.35A7.958 7.958 0 0 0 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0 1 12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>
					</svg>
				</button>
			</div>

			<!-- Messages -->
			<div class="lc-messages" ref="messagesEl">
				<div v-if="messages.length === 0" class="lc-welcome">
					<div class="lc-welcome-title">Hello, I am Logix</div>
					<div class="lc-welcome-sub">Your AI assistant for server scripts</div>
				</div>

				<div v-for="msg in messages" :key="msg.id" :class="['lc-msg-row', msg.role]">
					<div v-if="msg.role === 'assistant'" class="lc-avatar">
						<svg viewBox="0 0 24 24" fill="currentColor">
							<path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
						</svg>
					</div>
					<div class="lc-msg-body">
						<div :class="msg.role === 'user' ? 'lc-bubble-user' : 'lc-bubble-bot'">
							<template v-for="(part, pi) in parseMessage(msg.content)" :key="pi">
								<div v-if="part.type === 'text'" v-html="renderMarkdown(part.content)" class="lc-text-part"></div>
								<div v-else-if="part.type === 'code'" class="lc-code-block">
									<div class="lc-code-header">
										<span class="lc-code-lang">{{ part.lang || 'python' }}</span>
										<button class="lc-copy-btn" @click="copyCode(part.content, `${msg.id}-${pi}`)">
											<svg viewBox="0 0 24 24" fill="currentColor" width="12" height="12">
												<path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/>
											</svg>
											{{ copiedIndex === `${msg.id}-${pi}` ? 'Copied!' : 'Copy' }}
										</button>
									</div>
									<pre class="lc-code-pre"><code>{{ part.content }}</code></pre>
								</div>
							</template>
							<div v-if="msg.role === 'assistant'" class="lc-message-actions">
								<button class="lc-copy-msg-btn" @click="copyMsg(msg.content)" title="Copy">
									<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
										<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/>
										<path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>
									</svg>
								</button>
							</div>
						</div>
						<!-- Diff view for MODIFY -->
						<div v-if="msg.diffRows?.length" class="lc-split-diff">
							<div class="lc-split-header">
								<div class="lc-split-col-label">Original</div>
								<div class="lc-split-divider-head"></div>
								<div class="lc-split-col-label">Proposed</div>
							</div>
							<div class="lc-split-body">
								<div v-for="(row, ri) in msg.diffRows" :key="ri" class="lc-split-row">
									<pre :class="['lc-split-cell', splitCellClass(row, 'left')]">{{ row.left ?? '' }}</pre>
									<div class="lc-split-divider"></div>
									<pre :class="['lc-split-cell', splitCellClass(row, 'right')]">{{ row.right ?? '' }}</pre>
								</div>
							</div>
						</div>

						<!-- Tests panel for CREATE -->
						<div v-if="msg.testsChecklist?.length" class="lc-tests-panel">
							<div class="lc-tests-header">
								<svg viewBox="0 0 24 24" fill="currentColor" width="13" height="13"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
								Let's verify it works
							</div>
							<div class="lc-tests-intro">Click "Try this" on each scenario to confirm the script does what you expect.</div>
							<div class="lc-tests-checklist">
								<div v-for="(t, ti) in msg.testsChecklist" :key="ti" class="lc-test-item">
									<div class="lc-test-scenario">{{ t.scenario }}</div>
									<div class="lc-test-row"><span class="lc-test-label">When</span><span>{{ t.when }}</span></div>
									<div class="lc-test-row"><span class="lc-test-label">Expect</span><span>{{ t.expect }}</span></div>
									<div class="lc-test-actions">
										<button
											v-if="t.inputs && savedScriptName"
											class="lc-run-test-btn"
											:disabled="testRunResults[`${msg.id}-${ti}`]?.loading"
											@click="runTest(msg.id, ti, t.inputs)"
										>
											<span v-if="testRunResults[`${msg.id}-${ti}`]?.loading" class="lc-test-spinner"></span>
											<span v-else>▶ Try this</span>
										</button>
										<div v-if="testRunResults[`${msg.id}-${ti}`] && !testRunResults[`${msg.id}-${ti}`].loading" class="lc-test-result">
											<span :class="testRunResults[`${msg.id}-${ti}`].passed ? 'lc-test-pass' : 'lc-test-fail'">
												{{ testRunResults[`${msg.id}-${ti}`].passed ? '✓' : '✗' }}
												{{ testRunResults[`${msg.id}-${ti}`].summary }}
											</span>
										</div>
									</div>
								</div>
							</div>
						</div>

						<!-- Action buttons -->
						<div v-if="msg.actions?.length" class="lc-msg-actions">
							<button
								v-for="action in msg.actions"
								:key="action.handler + action.label"
								:class="['lc-action-btn', action.handler === 'reject_modify' ? 'lc-action-btn--reject' : '']"
								@click="handleAction(action, msg.id)"
							>{{ action.label }}</button>
						</div>
						<div class="lc-msg-time" :class="msg.role === 'user' ? 'lc-time-right' : 'lc-time-left'">{{ msg.time }}</div>
					</div>
				</div>

				<!-- Typing indicator -->
				<div v-if="isTyping" class="lc-msg-row assistant">
					<div class="lc-avatar">
						<svg viewBox="0 0 24 24" fill="currentColor">
							<path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
						</svg>
					</div>
					<div class="lc-msg-body">
						<div class="lc-bubble-bot lc-typing-bubble">
							<div class="lc-typing"><span></span><span></span><span></span></div>
						</div>
					</div>
				</div>
			</div>

			<!-- Input (Lumina style) -->
			<div class="lc-input-area">
				<div class="lc-toolbar-row">
					<div class="lc-toolbar">
						<button class="lc-toolbar-btn" @mousedown.prevent="execCmd('bold')" title="Bold"><b>B</b></button>
						<button class="lc-toolbar-btn" @mousedown.prevent="execCmd('italic')" title="Italic"><i>I</i></button>
						<button class="lc-toolbar-btn" @mousedown.prevent="execCmd('underline')" title="Underline"><u>U</u></button>
						<button class="lc-toolbar-btn" @mousedown.prevent="insertLink" title="Link">
							<svg viewBox="0 0 24 24" fill="currentColor" width="13" height="13"><path d="M3.9 12c0-1.71 1.39-3.1 3.1-3.1h4V7H7c-2.76 0-5 2.24-5 5s2.24 5 5 5h4v-1.9H7c-1.71 0-3.1-1.39-3.1-3.1zM8 13h8v-2H8v2zm9-6h-4v1.9h4c1.71 0 3.1 1.39 3.1 3.1s-1.39 3.1-3.1 3.1h-4V17h4c2.76 0 5-2.24 5-5s-2.24-5-5-5z"/></svg>
						</button>
						<button class="lc-toolbar-btn" @mousedown.prevent="execCmd('insertUnorderedList')" title="Bulleted list">
							<svg viewBox="0 0 24 24" fill="currentColor" width="13" height="13"><path d="M4 10.5c-.83 0-1.5.67-1.5 1.5s.67 1.5 1.5 1.5 1.5-.67 1.5-1.5-.67-1.5-1.5-1.5zm0-6c-.83 0-1.5.67-1.5 1.5S3.17 7.5 4 7.5 5.5 6.83 5.5 6 4.83 4.5 4 4.5zm0 12c-.83 0-1.5.68-1.5 1.5s.68 1.5 1.5 1.5 1.5-.68 1.5-1.5-.67-1.5-1.5-1.5zM7 19h14v-2H7v2zm0-6h14v-2H7v2zm0-8v2h14V5H7z"/></svg>
						</button>
						<button class="lc-toolbar-btn" @mousedown.prevent="execCmd('insertOrderedList')" title="Numbered list">
							<svg viewBox="0 0 24 24" fill="currentColor" width="13" height="13"><path d="M2 17h2v.5H3v1h1v.5H2v1h3v-4H2v1zm1-9h1V4H2v1h1v3zm-1 3h1.8L2 13.1v.9h3v-1H3.2L5 10.9V10H2v1zm5-6v2h14V5H7zm0 14h14v-2H7v2zm0-6h14v-2H7v2z"/></svg>
						</button>
					</div>
				</div>
				<div class="lc-editor-row">
					<div
						ref="inputEl"
						class="lc-editor"
						contenteditable="true"
						data-placeholder="Describe the script you need… (Enter to send)"
						@keydown="handleKeydown"
						@input="onEditorInput"
					></div>
					<button class="lc-send-btn" @click="sendMessage" :disabled="!editorHasContent || isTyping" title="Send">
						<svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18">
							<path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
						</svg>
					</button>
				</div>
			</div>
		</div>

		<!-- ── CENTER: Code Editor Panel ────────────────────────────── -->
		<div class="lc-editor-panel">

			<!-- File bar -->
			<div class="lc-file-bar">
				<div class="lc-file-name-area">
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="14" height="14">
						<path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"/>
					</svg>
					<span v-if="!isEditingName" class="lc-filename" @dblclick="startEditName" title="Double-click to rename">
						{{ canvasScriptName || 'Untitled' }}
					</span>
					<input
						v-else
						ref="nameInputEl"
						v-model="canvasScriptName"
						class="lc-name-input"
						placeholder="Script name..."
						@blur="stopEditName"
						@keydown.enter="stopEditName"
						@keydown.escape="stopEditName"
					/>
				</div>
				<div class="lc-file-actions">
					<!-- Save status -->
					<span v-if="isSaving" class="lc-save-status lc-autosaving">
						<span class="lc-spinner-sm"></span> Saving…
					</span>
					<span v-else-if="isDirty && !isSaved" class="lc-save-status lc-unsaved">● Unsaved</span>
					<span v-else-if="isSaved" class="lc-save-status lc-saved">✓ Saved</span>

					<div v-if="isLoadingScript" class="lc-loading-indicator">
						<div class="lc-spinner-sm"></div>
						Loading...
					</div>

					<!-- Folder / Script Browser button -->
					<div class="lc-script-browser-wrap">
						<button
							class="lc-file-btn"
							:class="{ 'lc-file-btn--active': showScriptBrowser }"
							@click="toggleScriptBrowser"
							title="Browse server scripts"
						>
							<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" width="14" height="14">
								<path stroke-linecap="round" stroke-linejoin="round" d="M3 7a2 2 0 012-2h3.5L10 7h9a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"/>
							</svg>
						</button>
						<!-- Script browser dropdown -->
						<div v-if="showScriptBrowser" class="lc-script-dropdown">
							<div class="lc-script-dropdown-header">
								<span>Server Scripts</span>
								<div v-if="loadingScriptBrowser" class="lc-spinner-sm"></div>
							</div>
							<div class="lc-script-dropdown-search">
								<input
									v-model="scriptBrowserSearch"
									type="text"
									placeholder="Search scripts..."
									class="lc-script-search-input"
									@click.stop
								/>
							</div>
							<div class="lc-script-dropdown-list">
								<div v-if="loadingScriptBrowser && !filteredScriptBrowserList.length" class="lc-script-dropdown-empty">Loading…</div>
								<div v-else-if="filteredScriptBrowserList.length === 0" class="lc-script-dropdown-empty">No scripts found</div>
								<div
									v-for="s in filteredScriptBrowserList"
									:key="s.name"
									class="lc-script-dropdown-item"
									:class="{ 'lc-script-dropdown-item--active': s.name === canvasScriptName }"
									@click="linkExistingScript(s.name)"
								>
									<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="12" height="12" class="lc-script-item-icon">
										<path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"/>
									</svg>
									<div class="lc-script-item-info">
										<div class="lc-script-item-name">{{ s.name }}</div>
										<div class="lc-script-item-type">{{ s.script_type }}</div>
									</div>
									<svg v-if="s.name === canvasScriptName" viewBox="0 0 24 24" fill="currentColor" width="12" height="12" class="lc-script-item-check">
										<path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
									</svg>
								</div>
							</div>
						</div>
					</div>

					<button class="lc-file-btn" @click="copyCanvas" title="Copy script">
						<svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14">
							<path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/>
						</svg>
						Copy
					</button>
					<button
						class="lc-file-btn"
						:class="{ 'lc-file-btn--active': showVersionHistory }"
						@click="showVersionHistory = !showVersionHistory"
						title="Version History"
					>
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" width="14" height="14">
							<circle cx="12" cy="12" r="10"/>
							<polyline points="12 6 12 12 16 14"/>
						</svg>
					</button>
				</div>
			</div>

			<!-- Backdrop to close dropdowns when clicking outside -->
			<div v-if="showDoctypeDropdown || showModuleDropdown || showScriptBrowser" class="lc-dropdown-backdrop" @click="showDoctypeDropdown = false; showModuleDropdown = false; showScriptBrowser = false"></div>

			<!-- Script Settings Panel -->
			<div class="lc-settings-panel">
					<div class="lc-settings-grid">
						<!-- Script Type -->
						<div class="lc-settings-field">
							<label class="lc-settings-label">Script Type</label>
							<select v-model="scriptMeta.script_type" class="lc-settings-select">
								<option value="API">API</option>
								<option value="DocType Event">DocType Event</option>
								<option value="Scheduler Event">Scheduler Event</option>
								<option value="Permission Query">Permission Query</option>
							</select>
						</div>

						<!-- Module -->
						<div class="lc-settings-field">
							<label class="lc-settings-label">Module</label>
							<div class="lc-settings-dropdown-wrap">
								<input
									v-model="moduleSearch"
									type="text"
									:placeholder="scriptMeta.module || 'Search Module...'"
									class="lc-settings-input"
									@focus="showModuleDropdown = true; showDoctypeDropdown = false; moduleSearch = ''"
								/>
								<div v-if="showModuleDropdown && filteredModuleOptions.length > 0" class="lc-settings-dropdown">
									<div v-for="m in filteredModuleOptions" :key="m" @mousedown.prevent="scriptMeta.module = m; moduleSearch = m; showModuleDropdown = false" class="lc-settings-dropdown-item">{{ m }}</div>
								</div>
							</div>
						</div>

						<!-- DocType (for DocType Event / Permission Query) -->
						<template v-if="['DocType Event', 'Permission Query'].includes(scriptMeta.script_type)">
							<div class="lc-settings-field">
								<label class="lc-settings-label">Reference DocType</label>
								<div class="lc-settings-dropdown-wrap">
									<input
										v-model="doctypeSearch"
										type="text"
										:placeholder="scriptMeta.reference_doctype || 'Search DocType...'"
										class="lc-settings-input"
										@focus="showDoctypeDropdown = true; showModuleDropdown = false; doctypeSearch = ''"
									/>
									<div v-if="showDoctypeDropdown && filteredDoctypeOptions.length > 0" class="lc-settings-dropdown">
										<div v-for="dt in filteredDoctypeOptions" :key="dt" @mousedown.prevent="scriptMeta.reference_doctype = dt; doctypeSearch = dt; showDoctypeDropdown = false" class="lc-settings-dropdown-item">{{ dt }}</div>
									</div>
								</div>
							</div>
							<div v-if="scriptMeta.script_type === 'DocType Event'" class="lc-settings-field">
								<label class="lc-settings-label">DocType Event</label>
								<select v-model="scriptMeta.doctype_event" class="lc-settings-select">
									<option value="">Select event...</option>
									<option v-for="e in DOCTYPE_EVENTS" :key="e" :value="e">{{ e }}</option>
								</select>
							</div>
						</template>

						<!-- API fields -->
						<template v-if="scriptMeta.script_type === 'API'">
							<div class="lc-settings-field">
								<label class="lc-settings-label">API Method</label>
								<input v-model="scriptMeta.api_method" type="text" placeholder="e.g. my_api" class="lc-settings-input" />
							</div>
							<div class="lc-settings-field lc-settings-field--inline">
								<label class="lc-settings-label">Allow Guest</label>
								<input type="checkbox" v-model="scriptMeta.allow_guest" class="lc-settings-checkbox" />
							</div>
						</template>

						<!-- Scheduler Event fields -->
						<template v-if="scriptMeta.script_type === 'Scheduler Event'">
							<div class="lc-settings-field">
								<label class="lc-settings-label">Event Frequency</label>
								<select v-model="scriptMeta.event_frequency" class="lc-settings-select">
									<option value="">Select frequency...</option>
									<option v-for="f in EVENT_FREQUENCIES" :key="f" :value="f">{{ f }}</option>
								</select>
							</div>
							<div v-if="scriptMeta.event_frequency === 'Cron'" class="lc-settings-field">
								<label class="lc-settings-label">Cron Format</label>
								<input v-model="scriptMeta.cron_format" type="text" placeholder="*/5 * * * *" class="lc-settings-input" />
							</div>
						</template>
					</div>
			</div>

			<!-- Code area with line numbers -->
			<div class="lc-code-area" ref="codeAreaEl">
				<div class="lc-line-numbers" ref="lineNumsEl" aria-hidden="true">
					<div v-for="n in lineCount" :key="n" class="lc-line-num">{{ n }}</div>
				</div>
				<textarea
					ref="codeTextareaEl"
					v-model="canvasCode"
					class="lc-code-textarea"
					spellcheck="false"
					placeholder="# Script will appear here after chatting with Logix or loading an existing script..."
					@input="onCodeInput"
					@scroll="syncScroll"
				></textarea>
			</div>

		</div>

		<!-- ── RIGHT: Version History Panel ──────────────────── -->
		<Transition name="lc-slide-in">
			<div v-if="showVersionHistory" class="lc-version-panel">
				<div class="lc-version-panel-header">
					<span>Version History</span>
					<button class="lc-ver-refresh-btn" @click="fetchVersionHistory" :disabled="loadingVersions" title="Refresh">
						<svg viewBox="0 0 24 24" fill="currentColor" width="13" height="13" :class="{ 'lc-spin': loadingVersions }">
							<path d="M17.65 6.35A7.958 7.958 0 0 0 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0 1 12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>
						</svg>
					</button>
				</div>

				<div v-if="loadingVersions" class="lc-version-empty">
					<div class="lc-ver-spinner"></div>
					<p>Loading history…</p>
				</div>
				<div v-else-if="!canvasScriptName" class="lc-version-empty">
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="28" height="28">
						<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
					</svg>
					<p>No script linked.</p>
					<p class="lc-version-empty-sub">Save the script first.</p>
				</div>
				<div v-else-if="versions.length === 0" class="lc-version-empty">
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="28" height="28">
						<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
					</svg>
					<p>No history yet.</p>
					<p class="lc-version-empty-sub">Save changes to start tracking versions.</p>
				</div>

				<div v-for="(v, idx) in versions" :key="v.version_name" class="lc-version-item" :class="{ 'lc-version-active': v.is_current }">
					<div class="lc-version-top">
						<div class="lc-version-top-left">
							<span class="lc-version-num">V{{ versions.length - idx }}</span>
							<span v-if="v.is_current" class="lc-active-badge">Current</span>
						</div>
						<span class="lc-version-time">{{ formatCreation(v.creation) }}</span>
					</div>
					<div class="lc-version-author">{{ v.author }}</div>
					<div class="lc-version-desc">{{ v.description }}</div>
					<div class="lc-version-links">
						<button v-if="!v.is_current" class="lc-ver-link" @click="toggleDiff(v)">[View Diff]</button>
						<button v-if="!v.is_current" class="lc-ver-link" @click="restoreVersion(v)">[Restore]</button>
					</div>
					<!-- Inline diff -->
					<div v-if="diffVersion?.version_name === v.version_name && versionDiffRows.length" class="lc-inline-diff">
						<div class="lc-inline-diff-header">
							<span>V{{ versions.length - idx }}</span>
							<span>Current</span>
						</div>
						<div class="lc-inline-diff-body">
							<div v-for="(row, ri) in versionDiffRows" :key="ri" class="lc-diff-row">
								<pre :class="['lc-diff-cell', diffCellClass(row, 'left')]">{{ row.left ?? '' }}</pre>
								<pre :class="['lc-diff-cell', diffCellClass(row, 'right')]">{{ row.right ?? '' }}</pre>
							</div>
						</div>
					</div>
				</div>
			</div>
		</Transition>
	</div>
</template>

<script setup>
import { ref, reactive, computed, nextTick, onMounted, watch } from "vue";
import DOMPurify from "dompurify";
import { marked } from "marked";

marked.setOptions({ gfm: true, breaks: true });

function getCsrfToken() {
	return (
		window.frappe?.csrf_token ||
		window.frappe?.boot?.csrf_token ||
		window.csrf_token ||
		document.cookie.split("; ").find(r => r.startsWith("csrf_token="))?.split("=")[1] ||
		""
	);
}

function getCurrentUser() {
	return window.frappe?.session?.user_fullname || window.frappe?.session?.user || "You";
}

const props = defineProps({
	element:        { type: Object,  default: null },
	scriptType:     { type: String,  default: "bpmn:script" },
	currentScript:  { type: String,  default: "" },
	eventBus:       { type: Object,  default: null },
	processContext: { type: Object,  default: null },
});

const emit = defineEmits(["close", "script-saved", "back"]);

// ── Canvas state ──────────────────────────────────────────────────────
const canvasScriptName = ref(props.currentScript || "");
const savedScriptName  = ref(props.currentScript || ""); // tracks the name currently in the DB
const canvasCode       = ref("");
const isEditingName    = ref(false);
const nameInputEl      = ref(null);
const isDirty          = ref(false);
const isSaving         = ref(false);
const isSaved          = ref(false);
const isLoadingScript  = ref(false);

// ── Auto-save ─────────────────────────────────────────────────────────
let autoSaveTimer = null;
let isInitializing = false;

// ── Script metadata ───────────────────────────────────────────────────
const scriptMeta = ref({
	script_type: "API",
	reference_doctype: "",
	doctype_event: "",
	api_method: "",
	allow_guest: false,
	event_frequency: "",
	cron_format: "",
	module: "",
});
const doctypeOptions = ref([]);
const moduleOptions  = ref([]);
const showDoctypeDropdown = ref(false);
const showModuleDropdown  = ref(false);
const doctypeSearch  = ref("");
const moduleSearch   = ref("");
const filteredDoctypeOptions = computed(() => {
	const q = doctypeSearch.value.toLowerCase();
	return q ? doctypeOptions.value.filter((d) => d.toLowerCase().includes(q)) : doctypeOptions.value;
});
const filteredModuleOptions = computed(() => {
	const q = moduleSearch.value.toLowerCase();
	return q ? moduleOptions.value.filter((m) => m.toLowerCase().includes(q)) : moduleOptions.value;
});

const DOCTYPE_EVENTS = [
	"Before Insert", "Before Validate", "Before Save", "After Insert",
	"After Save", "Before Rename", "After Rename", "Before Submit",
	"After Submit", "Before Cancel", "After Cancel", "Before Delete",
	"After Delete", "Before Save (Submitted Document)",
	"After Save (Submitted Document)", "Before Print", "On Payment Authorization",
];
const EVENT_FREQUENCIES = [
	"All", "Hourly", "Daily", "Weekly", "Monthly", "Yearly",
	"Hourly Long", "Daily Long", "Weekly Long", "Monthly Long", "Cron",
];

async function loadDoctypeOptions() {
	if (doctypeOptions.value.length) return;
	try {
		const r = await fetch("/api/method/frappe.client.get_list?doctype=DocType&fields=[%22name%22]&limit_page_length=0&order_by=name+asc", { headers: { "X-Frappe-CSRF-Token": getCsrfToken() } });
		const d = await r.json();
		doctypeOptions.value = (d?.message || []).map((x) => x.name);
	} catch (e) { console.error("Failed to load DocTypes", e); }
}
async function loadModuleOptions() {
	if (moduleOptions.value.length) return;
	try {
		const r = await fetch("/api/method/frappe.client.get_list?doctype=Module+Def&fields=[%22name%22]&limit_page_length=0&order_by=name+asc", { headers: { "X-Frappe-CSRF-Token": getCsrfToken() } });
		const d = await r.json();
		moduleOptions.value = (d?.message || []).map((x) => x.name);
	} catch (e) { console.error("Failed to load Modules", e); }
}

// ── Version history ───────────────────────────────────────────────────
const showVersionHistory = ref(false);
const versions           = ref([]);
const loadingVersions    = ref(false);
const diffVersion        = ref(null);
const versionDiffRows    = ref([]);

// ── Script browser ────────────────────────────────────────────────────
const showScriptBrowser    = ref(false);
const scriptBrowserList    = ref([]);
const loadingScriptBrowser = ref(false);
const scriptBrowserSearch  = ref("");

const filteredScriptBrowserList = computed(() => {
	const q = scriptBrowserSearch.value.toLowerCase();
	return q ? scriptBrowserList.value.filter(s => s.name.toLowerCase().includes(q) || (s.script_type || "").toLowerCase().includes(q)) : scriptBrowserList.value;
});

async function toggleScriptBrowser() {
	showScriptBrowser.value = !showScriptBrowser.value;
	if (showScriptBrowser.value && !scriptBrowserList.value.length) {
		await fetchScriptBrowserList();
	}
}

async function fetchScriptBrowserList() {
	loadingScriptBrowser.value = true;
	try {
		const r = await fetch(
			"/api/method/frappe.client.get_list?doctype=Server%20Script&fields=[%22name%22,%22script_type%22]&limit_page_length=0&order_by=modified+desc",
			{ headers: { "X-Frappe-CSRF-Token": getCsrfToken() } },
		);
		const d = await r.json();
		scriptBrowserList.value = d?.message || [];
	} catch (e) {
		console.error("Failed to load script list:", e);
	} finally {
		loadingScriptBrowser.value = false;
	}
}

async function linkExistingScript(name) {
	showScriptBrowser.value = false;
	isInitializing = true;
	try {
		canvasScriptName.value = name;
		savedScriptName.value  = name;
		isLoadingScript.value  = true;
		const resp = await fetch(
			`/api/method/frappe.client.get?doctype=Server%20Script&name=${encodeURIComponent(name)}`,
			{ headers: { "X-Frappe-CSRF-Token": getCsrfToken() } },
		);
		const data = await resp.json();
		const msg = data?.message || {};
		canvasCode.value = msg.script || "";
		scriptMeta.value = {
			script_type:       msg.script_type || "API",
			reference_doctype: msg.reference_doctype || "",
			doctype_event:     msg.doctype_event || "",
			api_method:        msg.api_method || "",
			allow_guest:       !!msg.allow_guest,
			event_frequency:   msg.event_frequency || "",
			cron_format:       msg.cron_format || "",
			module:            msg.module || "",
		};
		if (props.eventBus && props.element) {
			props.eventBus.fire("spiff.script.update", {
				element:    props.element,
				scriptType: props.scriptType,
				script:     name,
			});
		}
		isDirty.value = false;
		isSaved.value = false;
		await fetchVersionHistory();
		messages.value.push({
			id: makeId(), role: "assistant", time: formatTime(new Date()),
			content: `Loaded **${name}** into the canvas. What changes would you like to make?`,
		});
		scrollBottom();
	} catch (e) {
		console.error("Failed to link script:", e);
	} finally {
		isLoadingScript.value = false;
		isInitializing = false;
	}
}

// ── Chat state ────────────────────────────────────────────────────────
const messages          = ref([]);
const editorHasContent  = ref(false);
const isTyping          = ref(false);
const sessionId         = ref(generateSessionId());
const conversationName  = ref(null);   // persisted Chat Conversation name
const messagesEl        = ref(null);
const inputEl           = ref(null);
const copiedIndex       = ref(null);
const testRunResults    = reactive({});  // key: `${msgId}-${ti}` → { loading, passed, summary }
let   pendingLogixDescription = "";
let   pendingScriptName       = "";

// ── Code editor refs ──────────────────────────────────────────────────
const codeAreaEl      = ref(null);
const lineNumsEl      = ref(null);
const codeTextareaEl  = ref(null);

const lineCount = computed(() => Math.max(1, (canvasCode.value || "").split("\n").length));

// ── Element label ─────────────────────────────────────────────────────
const elementLabel = computed(() => {
	if (!props.element) return "";
	const bo = props.element.businessObject;
	return bo?.name || props.element.id || "";
});

// ── Lifecycle ─────────────────────────────────────────────────────────
onMounted(async () => {
	loadDoctypeOptions();
	loadModuleOptions();
	await initCanvas();
	initGreeting();
	nextTick(() => inputEl.value?.focus());
});

async function initCanvas() {
	isInitializing = true;
	try {
		if (props.currentScript) {
			canvasScriptName.value = props.currentScript;
			savedScriptName.value  = props.currentScript;
			isLoadingScript.value  = true;
			try {
				const resp = await fetch(
					`/api/method/frappe.client.get?doctype=Server%20Script&name=${encodeURIComponent(props.currentScript)}`,
					{ headers: { "X-Frappe-CSRF-Token": getCsrfToken() } },
				);
				const data = await resp.json();
				const msg = data?.message || {};
				canvasCode.value = msg.script || "";
				scriptMeta.value = {
					script_type:       msg.script_type || "API",
					reference_doctype: msg.reference_doctype || "",
					doctype_event:     msg.doctype_event || "",
					api_method:        msg.api_method || "",
					allow_guest:       !!msg.allow_guest,
					event_frequency:   msg.event_frequency || "",
					cron_format:       msg.cron_format || "",
					module:            msg.module || "",
				};
			} catch (e) {
				console.error("Failed to load script:", e);
			} finally {
				isLoadingScript.value = false;
			}
			await fetchVersionHistory();
		} else {
			// Auto-set display name from the BPMN element label; savedScriptName stays ""
			// until the first successful auto-save confirms it exists in the DB.
			canvasScriptName.value = elementLabel.value || "";
			savedScriptName.value  = "";
			canvasCode.value = "";
			if (props.element?.type === "bpmn:ScriptTask") {
				scriptMeta.value.script_type = "API";
			}
		}
	} finally {
		isInitializing = false;
	}
}

// ── Greeting ──────────────────────────────────────────────────────────
function buildContextSentence() {
	const ctx = props.processContext;
	if (!ctx) return "";
	const parts = [];
	if (ctx.incoming?.length) {
		const names = ctx.incoming.map(n => `**${n.name}**`).join(" and ");
		parts.push(`runs after ${names}`);
	}
	if (ctx.outgoing?.length) {
		const names = ctx.outgoing.map(n => `**${n.name}**`).join(" and ");
		parts.push(`leads to ${names}`);
	}
	if (!parts.length) return "";
	return " I can see this task " + parts.join(", and ") + ".";
}

async function initGreeting() {
	const label   = canvasScriptName.value || elementLabel.value;
	const ctxLine = buildContextSentence();

	// Already linked to a known script — offer to help modify it
	if (props.currentScript) {
		messages.value = [{
			id: makeId(), role: "assistant", time: formatTime(new Date()),
			content: `Hello, I am Logix — your process automation assistant.${ctxLine}\n\nI can see **${props.currentScript}** is already linked here. How would you like to change it? Just describe what you need in plain language.`,
		}];
		return;
	}

	if (label) {
		// Check whether a Server Script with the same name already exists
		try {
			const resp = await fetch(
				`/api/method/one_bpmn.api.check_server_script_exists?script_name=${encodeURIComponent(label)}`,
				{ headers: { "X-Frappe-CSRF-Token": getCsrfToken() } },
			);
			if (resp.ok) {
				const data = await resp.json();
				if (data?.message?.exists) {
					messages.value = [{
						id: makeId(), role: "assistant", time: formatTime(new Date()),
						content: `Hello, I am Logix — your process automation assistant.${ctxLine}\n\nI found an existing script named **${label}**. Would you like to link it here, or start fresh with a new one?`,
						actions: [
							{ label: "Link to script task", handler: "link_existing" },
							{ label: "Create new",           handler: "start_fresh"  },
						],
					}];
					return;
				}
			}
		} catch (_) { /* fall through */ }

		const contextHint = ctxLine
			? `\n\nTell me in plain language what should happen at this step — for example, what data needs to be checked, what approval is needed, or what records should be updated.`
			: `\n\nDescribe what you'd like the script to do and I'll write it for you.`;
		messages.value = [{
			id: makeId(), role: "assistant", time: formatTime(new Date()),
			content: `Hello, I am Logix — your process automation assistant.${ctxLine}${contextHint}`,
		}];
		return;
	}

	messages.value = [{
		id: makeId(), role: "assistant", time: formatTime(new Date()),
		content: "Hello, I am Logix — your process automation assistant.\n\nDescribe what you'd like the script to do and I'll write it for you. You don't need to know any code — just tell me what the business logic should be.",
	}];
}

// ── Helpers ───────────────────────────────────────────────────────────
function generateSessionId() {
	return "logix_canvas_" + Date.now() + "_" + Math.random().toString(36).slice(2, 9);
}

function formatTime(d) {
	return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function makeId() {
	return Date.now() + "_" + Math.random().toString(36).slice(2, 7);
}

function scrollBottom() {
	nextTick(() => {
		if (messagesEl.value)
			messagesEl.value.scrollTop = messagesEl.value.scrollHeight;
	});
}

// ── Markdown ──────────────────────────────────────────────────────────
function renderMarkdown(text) {
	if (!text) return "";
	const html = marked.parse(text);
	return DOMPurify.sanitize(html, {
		ALLOWED_TAGS: ["b","i","u","s","strong","em","strike","del","a","p","br","div","span",
			"ul","ol","li","h1","h2","h3","h4","h5","h6","code","pre","blockquote","hr",
			"table","thead","tbody","tr","th","td"],
		ALLOWED_ATTR: ["href","title","target","rel","src","alt","width","height","class","align"],
		ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto):)/i,
	});
}

// ── Chat editor helpers ───────────────────────────────────────────────
function onEditorInput() {
	editorHasContent.value = !!(inputEl.value?.innerText?.trim());
}

function getEditorText() {
	return (inputEl.value?.innerText || inputEl.value?.textContent || "").trim();
}

function clearEditor() {
	if (inputEl.value) {
		inputEl.value.innerHTML = "";
		editorHasContent.value = false;
	}
}

function execCmd(cmd) {
	document.execCommand(cmd, false, null);
	inputEl.value?.focus();
}

function insertLink() {
	const url = prompt("Enter URL:");
	if (url) document.execCommand("createLink", false, url);
	inputEl.value?.focus();
}

// ── Code editor helpers ───────────────────────────────────────────────
function onCodeInput() {
	isDirty.value = true;
	isSaved.value = false;
	scheduleAutoSave();
}

function syncScroll() {
	if (lineNumsEl.value && codeTextareaEl.value) {
		lineNumsEl.value.scrollTop = codeTextareaEl.value.scrollTop;
	}
}

function startEditName() {
	isEditingName.value = true;
	nextTick(() => {
		nameInputEl.value?.select();
	});
}

async function stopEditName() {
	isEditingName.value = false;
	const newName = canvasScriptName.value.trim();
	if (newName && newName !== savedScriptName.value) {
		// New name — ensure it doesn't collide with an unrelated existing script
		await ensureUniqueName();
	}
	scheduleAutoSave();
}

async function copyCanvas() {
	try { await navigator.clipboard.writeText(canvasCode.value); } catch { /* fallback */ }
}

// ── Message action handler ────────────────────────────────────────────
async function handleAction(action, msgId) {
	const msg = messages.value.find(m => m.id === msgId);

	if (action.handler === "link_existing") {
		if (msg) msg.actions = null;
		// Load the script content into the canvas
		await initCanvas();
		// Fire the BPMN event to link the existing script to the element
		if (props.eventBus && props.element) {
			props.eventBus.fire("spiff.script.update", {
				element:    props.element,
				scriptType: props.scriptType,
				script:     canvasScriptName.value,
			});
		}
		messages.value.push({
			id: makeId(), role: "assistant", time: formatTime(new Date()),
			content: `**${canvasScriptName.value}** has been linked to this script task. What changes would you like to make?`,
		});
		scrollBottom();

	} else if (action.handler === "start_fresh") {
		if (msg) msg.actions = null;
		canvasCode.value = "";
		messages.value.push({
			id: makeId(), role: "assistant", time: formatTime(new Date()),
			content: "Canvas cleared. Describe what the script should do and I'll write it for you.",
		});
		scrollBottom();
		nextTick(() => inputEl.value?.focus());

	} else if (action.handler === "clarify") {
		if (msg) msg.actions = null;
		if (inputEl.value) {
			inputEl.value.innerText = action.value || "";
			editorHasContent.value = true;
		}
		sendMessage();

	} else if (action.handler === "approve_modify") {
		if (msg) msg.actions = null;
		const code = msg?.pendingCode || "";
		if (code) {
			canvasCode.value = code;
			isDirty.value = true;
			isSaved.value = false;
			pendingLogixDescription = msg?.pendingDescription || "Modified by Logix";
			const saveResult = await saveScript();
			if (isDirty.value) {
				messages.value.push({
					id: makeId(), role: "assistant", time: formatTime(new Date()),
					content: "Changes applied but save failed — check the script name and try again.",
				});
			} else {
				messages.value.push({
					id: makeId(), role: "assistant", time: formatTime(new Date()),
					content: "Changes approved and saved ✓",
				});
			}
		} else {
			messages.value.push({
				id: makeId(), role: "assistant", time: formatTime(new Date()),
				content: "Changes approved ✓",
			});
		}
		scrollBottom();

	} else if (action.handler === "reject_modify") {
		if (msg) msg.actions = null;
		messages.value.push({
			id: makeId(), role: "assistant", time: formatTime(new Date()),
			content: "Changes rejected. The existing script is unchanged. Let me know how you'd like to adjust the modification.",
		});
		scrollBottom();

	} else if (action.handler === "approve_create") {
		if (msg) msg.actions = null;
		const code = msg?.pendingCode || "";
		if (code) {
			canvasCode.value = code;
			isDirty.value = true;
			isSaved.value = false;
			pendingLogixDescription = msg?.pendingDescription || "Created by Logix";
			if (msg?.pendingName && !props.currentScript) {
				canvasScriptName.value = msg.pendingName;
			}
			await saveScript();
		}
		const savedOk = !isDirty.value;
		messages.value.push({
			id: makeId(), role: "assistant", time: formatTime(new Date()),
			content: savedOk
				? "Your automation is saved and ready ✓\n\nHere are a few quick checks you can run to make sure it does exactly what you need — no coding required."
				: "Script applied but save failed — check the script name and try again.",
		});

		// Show tests panel if we have them
		const checklist = msg?.testsChecklist || [];
		if (savedOk && checklist.length) {
			messages.value.push({
				id: makeId(), role: "assistant", time: formatTime(new Date()),
				content: "",
				testsChecklist: checklist,
			});
		}
		scrollBottom();

	} else if (action.handler === "apply_to_canvas") {
		if (msg) msg.actions = null;
		const code = msg?.pendingCode || "";
		if (code) {
			canvasCode.value = code;
			isDirty.value = true;
			isSaved.value = false;
			pendingLogixDescription = msg?.pendingDescription || "Updated by Logix";
			if (msg?.pendingName && !props.currentScript) {
				canvasScriptName.value = msg.pendingName;
			}
			scheduleAutoSave();
		}
		messages.value.push({
			id: makeId(), role: "assistant", time: formatTime(new Date()),
			content: "Script applied to the canvas ✓\nReview the code on the right and edit if needed — it will auto-save shortly.",
		});
		scrollBottom();
	}
}

// ── Send / receive ────────────────────────────────────────────────────
function handleKeydown(e) {
	if (e.key === "Enter" && !e.shiftKey) {
		e.preventDefault();
		sendMessage();
	}
}

async function sendMessage() {
	const text = getEditorText();
	if (!text || isTyping.value) return;

	clearEditor();
	messages.value.push({ id: makeId(), role: "user", content: text, time: formatTime(new Date()) });
	scrollBottom();
	isTyping.value = true;

	try {
		const history = messages.value
			.slice(-10)
			.map(m => ({ type: m.role, content: m.content }));

		const response = await fetch("/api/method/one_bpmn.api.process_logix_message", {
			method: "POST",
			headers: {
				"Content-Type":       "application/json",
				"X-Frappe-CSRF-Token": getCsrfToken(),
			},
			body: JSON.stringify({
				message:           text,
				session_id:        sessionId.value,
				conversation_name: conversationName.value || null,
				element_name:      elementLabel.value || canvasScriptName.value || "",
				current_script:    props.currentScript || "",
				process_context:   props.processContext || null,
			}),
		});

		if (!response.ok) throw new Error(`HTTP ${response.status}`);
		const data   = await response.json();
		const result = data?.message;

		// Capture the conversation name returned by the backend
		if (result?.conversation_name) conversationName.value = result.conversation_name;

		const reply  = result?.response || result?.message || "Sorry, I couldn't process that.";
		const intent = result?.intent;
		const diff   = result?.diff || null;
		const options = result?.options || null;

		const msg = {
			id: makeId(), role: "assistant", content: reply,
			time: formatTime(new Date()), intent,
		};

		if (intent === "DISAMBIGUATE" && options?.length) {
			msg.actions = options.map(o => ({ label: o, handler: "clarify", value: o }));

		} else if (intent === "MODIFY") {
			const proposedCode = result?.modified_script || extractCode(reply);
			if (diff) msg.diffRows = parseSplitDiff(diff);
			msg.pendingCode = proposedCode;
			msg.pendingDescription = "Modified by Logix";
			if (/```python[\s\S]*?```/.test(reply)) {
				msg.actions = [
					{ label: "Approve & Save", handler: "approve_modify" },
					{ label: "Reject",         handler: "reject_modify"  },
				];
			}

		} else if (intent === "CREATE") {
			const proposedCode = result?.modified_script || extractCode(reply);
			msg.pendingCode = proposedCode;
			msg.pendingName = result?.suggested_name || "";
			msg.pendingDescription = `Created by Logix${result?.suggested_name ? ': ' + result.suggested_name : ''}`;
			msg.testsChecklist = result?.tests_checklist || [];
			if (/```python[\s\S]*?```/.test(reply)) {
				msg.actions = [{ label: "Approve & Save", handler: "approve_create" }];
			}
		}

		messages.value.push(msg);
	} catch (err) {
		console.error("Logix error:", err);
		messages.value.push({
			id: makeId(), role: "assistant",
			content: "Sorry, I encountered an error. Please try again.",
			time: formatTime(new Date()),
		});
	} finally {
		isTyping.value = false;
		scrollBottom();
		nextTick(() => inputEl.value?.focus());
	}
}

// ── Parse message & format ────────────────────────────────────────────
function parseMessage(content) {
	const parts = [];
	const re    = /```(\w*)\n?([\s\S]*?)```/g;
	let last = 0, match;
	while ((match = re.exec(content)) !== null) {
		if (match.index > last)
			parts.push({ type: "text", content: content.slice(last, match.index) });
		parts.push({ type: "code", lang: match[1] || "python", content: match[2].trim() });
		last = match.index + match[0].length;
	}
	if (last < content.length)
		parts.push({ type: "text", content: content.slice(last) });
	return parts;
}

function extractCode(text) {
	const m = (text || "").match(/```python\s*\n([\s\S]*?)```/);
	return m ? m[1].trim() : (text || "").trim();
}

// ── Chat copy ─────────────────────────────────────────────────────────
async function copyCode(code, index) {
	try {
		await navigator.clipboard.writeText(code);
		copiedIndex.value = index;
		setTimeout(() => { copiedIndex.value = null; }, 2000);
	} catch { /* fallback */ }
}

async function copyMsg(content) {
	try { await navigator.clipboard.writeText(content); } catch { /* fallback */ }
}

// ── Test runner ───────────────────────────────────────────────────────
async function runTest(msgId, ti, inputs) {
	const key = `${msgId}-${ti}`;
	testRunResults[key] = { loading: true, passed: null, summary: "" };
	try {
		const response = await fetch("/api/method/one_bpmn.api.run_logix_test_case", {
			method: "POST",
			headers: {
				"Content-Type":        "application/json",
				"X-Frappe-CSRF-Token": getCsrfToken(),
			},
			body: JSON.stringify({
				script_name: savedScriptName.value,
				inputs:      JSON.stringify(inputs || {}),
			}),
		});
		const data   = await response.json();
		const result = data?.message;
		testRunResults[key] = {
			loading: false,
			passed:  result?.passed ?? false,
			summary: result?.summary || (result?.passed ? "Test passed." : "Test failed."),
		};
	} catch (err) {
		testRunResults[key] = { loading: false, passed: false, summary: "Could not run the test — network error." };
	}
}

// ── Diff helpers ──────────────────────────────────────────────────────
function parseSplitDiff(unifiedDiff) {
	const rows  = [];
	const lines = (unifiedDiff || "").split("\n");
	let i = 0;
	while (i < lines.length && (lines[i].startsWith("---") || lines[i].startsWith("+++"))) i++;
	while (i < lines.length) {
		const line = lines[i];
		if (!line || line.startsWith("\\")) { i++; continue; }
		if (line.startsWith("@@")) { rows.push({ type: "hunk", left: line, right: line }); i++; continue; }
		if (line.startsWith("-")) {
			const left = line.slice(1);
			if (i + 1 < lines.length && lines[i + 1].startsWith("+")) {
				rows.push({ type: "changed", left, right: lines[i + 1].slice(1) });
				i += 2;
			} else { rows.push({ type: "deleted", left, right: null }); i++; }
		} else if (line.startsWith("+")) {
			rows.push({ type: "added", left: null, right: line.slice(1) }); i++;
		} else {
			rows.push({ type: "unchanged", left: line.startsWith(" ") ? line.slice(1) : line, right: line.startsWith(" ") ? line.slice(1) : line });
			i++;
		}
	}
	return rows;
}

function splitCellClass(row, side) {
	if (row.type === "hunk")      return "lc-sdiff-hunk";
	if (row.type === "unchanged") return "";
	if (row.type === "deleted")   return side === "left"  ? "lc-sdiff-del"  : "lc-sdiff-empty";
	if (row.type === "added")     return side === "right" ? "lc-sdiff-add"  : "lc-sdiff-empty";
	if (row.type === "changed")   return side === "left"  ? "lc-sdiff-del"  : "lc-sdiff-add";
	return "";
}

// ── Version history (real API) ───────────────────────────────────────
async function fetchVersionHistory() {
	if (!canvasScriptName.value) { versions.value = []; return; }
	loadingVersions.value = true;
	try {
		const res = await fetch(
			`/api/method/one_bpmn.api.get_script_version_history?script_name=${encodeURIComponent(canvasScriptName.value)}`,
			{ headers: { "X-Frappe-CSRF-Token": getCsrfToken() } }
		);
		const data = await res.json();
		versions.value = data?.message || [];
	} catch (e) {
		console.error("Failed to fetch version history:", e);
		versions.value = [];
	} finally {
		loadingVersions.value = false;
	}
}

function formatCreation(creation) {
	if (!creation) return "";
	try {
		return new Date(creation).toLocaleString(undefined, {
			month: "short", day: "numeric",
			hour: "2-digit", minute: "2-digit"
		});
	} catch { return creation; }
}

function toggleDiff(version) {
	if (diffVersion.value?.version_name === version.version_name) {
		diffVersion.value = null;
		versionDiffRows.value = [];
		return;
	}
	diffVersion.value = version;
	const oldLines = (version.script || "").split("\n");
	const newLines = (canvasCode.value || "").split("\n");
	const rows = [];
	const maxLen = Math.max(oldLines.length, newLines.length);
	for (let i = 0; i < maxLen; i++) {
		const l = oldLines[i] ?? null;
		const r = newLines[i] ?? null;
		if (l === r) rows.push({ type: "unchanged", left: l, right: r });
		else if (l === null) rows.push({ type: "added", left: null, right: r });
		else if (r === null) rows.push({ type: "deleted", left: l, right: null });
		else rows.push({ type: "changed", left: l, right: r });
	}
	versionDiffRows.value = rows;
}

function diffCellClass(row, side) {
	if (row.type === "hunk")      return "lc-sdiff-hunk";
	if (row.type === "unchanged") return "";
	if (row.type === "deleted")   return side === "left"  ? "lc-sdiff-del"  : "lc-sdiff-empty";
	if (row.type === "added")     return side === "right" ? "lc-sdiff-add"  : "lc-sdiff-empty";
	if (row.type === "changed")   return side === "left"  ? "lc-sdiff-del"  : "lc-sdiff-add";
	return "";
}

async function restoreVersion(version) {
	const versionNum = versions.value.length - versions.value.indexOf(version);
	canvasCode.value  = version.script || "";
	isDirty.value     = true;
	isSaved.value     = false;
	diffVersion.value = null;
	pendingLogixDescription = `Restored to V${versionNum}`;
	messages.value.push({
		id: makeId(), role: "assistant", time: formatTime(new Date()),
		content: `Restored canvas to V${versionNum}. Auto-saving…`,
	});
	scheduleAutoSave();
	scrollBottom();
}

// ── Auto-save scheduler ───────────────────────────────────────────────
function scheduleAutoSave() {
	if (isInitializing) return;
	if (autoSaveTimer) clearTimeout(autoSaveTimer);
	autoSaveTimer = setTimeout(() => { saveScript(); }, 1500);
}

// Watch metadata changes and auto-save
watch(scriptMeta, () => { scheduleAutoSave(); }, { deep: true });

// ── Unique name helper ────────────────────────────────────────────────
async function ensureUniqueName() {
	const base = canvasScriptName.value.trim();
	if (!base) return;
	let name = base;
	let counter = 1;
	while (true) {
		try {
			// A name that matches the currently saved script is always fine (it's ours)
			if (name === savedScriptName.value) break;
			const r = await fetch(
				`/api/method/one_bpmn.api.check_server_script_exists?script_name=${encodeURIComponent(name)}`,
				{ headers: { "X-Frappe-CSRF-Token": getCsrfToken() } },
			);
			const d = await r.json();
			if (!d?.message?.exists) break;
			name = `${base} ${counter++}`;
		} catch { break; }
	}
	canvasScriptName.value = name;
}

// ── Save script ───────────────────────────────────────────────────────
async function saveScript() {
	const name = canvasScriptName.value.trim();
	if (!name) return; // silently wait — user hasn't named the script yet

	isSaving.value = true;
	try {
		// If the script was previously saved under a different name, rename it first
		if (savedScriptName.value && savedScriptName.value !== name) {
			const renameRes = await fetch("/api/method/frappe.client.rename_doc", {
				method:  "POST",
				headers: { "Content-Type": "application/json", "X-Frappe-CSRF-Token": getCsrfToken() },
				body:    JSON.stringify({ doctype: "Server Script", name: savedScriptName.value, new_name: name }),
			});
			if (!renameRes.ok) throw new Error(`Rename failed: HTTP ${renameRes.status}`);
			savedScriptName.value = name;
		}

		// Upsert with the (possibly renamed) name
		const meta = scriptMeta.value;
		const res = await fetch("/api/method/one_bpmn.api.create_server_script", {
			method:  "POST",
			headers: { "Content-Type": "application/json", "X-Frappe-CSRF-Token": getCsrfToken() },
			body:    JSON.stringify({
				script_name:       name,
				script_type:       meta.script_type || "API",
				script:            canvasCode.value,
				reference_doctype: meta.reference_doctype || undefined,
				doctype_event:     meta.doctype_event || undefined,
				api_method:        meta.api_method || undefined,
				allow_guest:       meta.allow_guest ? 1 : 0,
				event_frequency:   meta.event_frequency || undefined,
				cron_format:       meta.cron_format || undefined,
				module:            meta.module || undefined,
			}),
		});
		if (!res.ok) throw new Error(`HTTP ${res.status}`);
		const data = await res.json();
		const scriptName = data?.message?.name || name;
		canvasScriptName.value = scriptName;
		savedScriptName.value  = scriptName;

		// Fire BPMN event to link the script to the element
		if (props.eventBus && props.element) {
			props.eventBus.fire("spiff.script.update", {
				element:    props.element,
				scriptType: props.scriptType,
				script:     scriptName,
			});
		}

		isDirty.value = false;
		isSaved.value = true;
		setTimeout(() => { isSaved.value = false; }, 3000);

		pendingLogixDescription = "";
		emit("script-saved", scriptName);
		await fetchVersionHistory();
	} catch (err) {
		console.error("Auto-save failed:", err);
	} finally {
		isSaving.value = false;
	}
}

// ── Reset chat ────────────────────────────────────────────────────────
function resetChat() {
	sessionId.value        = generateSessionId();
	conversationName.value = null;
	messages.value         = [];
	initGreeting();
}
</script>

<style scoped>
/* ── Root: 3-pane flex layout ───────────────────────────────────────── */
.lc-root {
	display: flex;
	flex-direction: row;
	height: 84vh;
	min-height: 560px;
	overflow: hidden;
	font-family: "Google Sans", Roboto, "Segoe UI", system-ui, sans-serif;
	background: #fff;
}

/* ═══════════════════════════════════════════════════════════════════
   CHAT PANEL (left)
══════════════════════════════════════════════════════════════════ */
.lc-chat-panel {
	width: 580px;
	flex-shrink: 0;
	display: flex;
	flex-direction: column;
	border-right: 1px solid #eee;
	background: #fff;
	min-width: 0;
}

/* ── Chat header ────────────────────────────────────────────────── */
.lc-chat-header {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 10px 14px;
	background: linear-gradient(135deg, #6c3fe0 0%, #9b59b6 100%);
	flex-shrink: 0;
}

.lc-chat-header-left {
	display: flex;
	align-items: center;
	gap: 8px;
	min-width: 0;
}


.lc-header-avatar {
	width: 26px;
	height: 26px;
	border-radius: 50%;
	background: rgba(255,255,255,0.2);
	display: flex;
	align-items: center;
	justify-content: center;
	flex-shrink: 0;
	color: #fff;
}

.lc-header-title {
	font-size: 13px;
	font-weight: 600;
	color: #fff;
}

.lc-header-chip {
	background: rgba(255,255,255,0.2);
	border: 1px solid rgba(255,255,255,0.3);
	border-radius: 4px;
	padding: 1px 7px;
	font-size: 11px;
	color: rgba(255,255,255,0.9);
	max-width: 100px;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}

.lc-header-btn {
	width: 26px;
	height: 26px;
	border: none;
	border-radius: 50%;
	background: rgba(255,255,255,0.15);
	color: #fff;
	cursor: pointer;
	display: flex;
	align-items: center;
	justify-content: center;
	transition: background 0.15s;
}

.lc-header-btn:hover { background: rgba(255,255,255,0.28); }

/* ── Messages ───────────────────────────────────────────────────── */
.lc-messages {
	flex: 1;
	overflow-y: auto;
	padding: 14px 12px 8px;
	background: #fff;
	display: flex;
	flex-direction: column;
	gap: 12px;
}

.lc-messages::-webkit-scrollbar { width: 4px; }
.lc-messages::-webkit-scrollbar-track { background: transparent; }
.lc-messages::-webkit-scrollbar-thumb { background: #ddd; border-radius: 2px; }

/* ── Welcome ────────────────────────────────────────────────────── */
.lc-welcome {
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	flex: 1;
	text-align: center;
	padding-top: 40px;
}

.lc-welcome-title { font-size: 1.1em; color: #444; font-weight: 500; margin-bottom: 6px; }
.lc-welcome-sub   { font-size: 0.88em; color: #888; }

/* ── Message rows ───────────────────────────────────────────────── */
.lc-msg-row {
	display: flex;
	flex-direction: row;
	gap: 7px;
	align-items: flex-start;
	width: 100%;
}

.lc-msg-row.user      { flex-direction: row-reverse; }
.lc-msg-row.assistant { /* stretches to full width by default */ }

/* ── Avatar ─────────────────────────────────────────────────────── */
.lc-avatar {
	width: 26px;
	height: 26px;
	border-radius: 50%;
	background: linear-gradient(135deg, #6c3fe0 0%, #9b59b6 100%);
	display: flex;
	align-items: center;
	justify-content: center;
	flex-shrink: 0;
	margin-top: 2px;
	color: #fff;
}

.lc-avatar svg { width: 13px; height: 13px; fill: #fff; }

/* ── Message body ───────────────────────────────────────────────── */
.lc-msg-body {
	display: flex;
	flex-direction: column;
	gap: 2px;
	min-width: 0;
}

.lc-msg-row.user .lc-msg-body      { align-items: flex-end; max-width: 80%; }
.lc-msg-row.assistant .lc-msg-body { align-items: flex-start; max-width: calc(100% - 36px); }

/* ── Bubbles (Lumina style) ─────────────────────────────────────── */
.lc-bubble-user {
	background: linear-gradient(135deg, #6c3fe0 0%, #9b59b6 100%);
	color: #fff;
	padding: 9px 13px;
	border-radius: 16px 16px 4px 16px;
	font-size: 0.88em;
	box-shadow: 0 2px 8px rgba(108,63,224,.25);
	overflow-wrap: break-word;
	word-break: break-word;
}

.lc-bubble-bot {
	background: #f7f7fa;
	color: #000;
	padding: 9px 13px;
	border-radius: 16px 16px 16px 4px;
	font-size: 0.88em;
	box-shadow: 0 1px 4px rgba(0,0,0,.04);
	overflow-wrap: break-word;
	word-break: break-word;
	display: flex;
	flex-direction: column;
}

/* ── Text parts ─────────────────────────────────────────────────── */
.lc-text-part { margin: 0; line-height: 1.55; }
.lc-text-part :deep(p) { margin: 0 0 4px; }
.lc-text-part :deep(p:last-child) { margin-bottom: 0; }
.lc-text-part :deep(ul), .lc-text-part :deep(ol) { margin: 3px 0 3px 1.2em; }
.lc-text-part :deep(code) { background: #ebebeb; border-radius: 3px; padding: 1px 4px; font-family: monospace; font-size: 0.88em; color: #333; }
.lc-bubble-user .lc-text-part :deep(code) { background: rgba(255,255,255,0.2); color: #fff; }

/* ── Timestamp ──────────────────────────────────────────────────── */
.lc-msg-time { font-size: 0.76em; color: #888; margin-top: 1px; }
.lc-time-right { text-align: right; }
.lc-time-left  { text-align: left; }

/* ── Copy button on bot messages ────────────────────────────────── */
.lc-message-actions {
	margin-top: 5px;
	display: flex;
	gap: 4px;
	opacity: 0.5;
	transition: opacity 0.18s;
}

.lc-bubble-bot:hover .lc-message-actions { opacity: 1; }

.lc-copy-msg-btn {
	background: transparent;
	border: none;
	padding: 2px;
	cursor: pointer;
	color: #777;
	display: flex;
	align-items: center;
	border-radius: 3px;
	transition: background 0.15s;
}

.lc-copy-msg-btn:hover { background: rgba(0,0,0,.08); color: #333; }

/* ── Code block in messages ─────────────────────────────────────── */
.lc-code-block {
	margin: 6px -2px 3px;
	border-radius: 6px;
	overflow: hidden;
	border: 1px solid #e0e0e0;
}

.lc-code-header {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 4px 10px;
	background: #f5f5f5;
}

.lc-code-lang {
	font-size: 10px;
	font-weight: 600;
	color: #666;
	text-transform: uppercase;
	letter-spacing: .4px;
	font-family: monospace;
}

.lc-copy-btn {
	display: flex;
	align-items: center;
	gap: 3px;
	border: none;
	border-radius: 4px;
	padding: 3px 7px;
	font-size: 11px;
	font-weight: 500;
	cursor: pointer;
	background: rgba(0,0,0,.06);
	color: #444;
	transition: background 0.15s;
	font-family: inherit;
}

.lc-copy-btn:hover { background: rgba(0,0,0,.12); }

.lc-code-pre {
	margin: 0;
	padding: 10px 12px;
	background: #1c1b1f;
	color: #e6e1e5;
	font-family: "JetBrains Mono", "Fira Code", monospace;
	font-size: 12px;
	line-height: 1.5;
	overflow-x: auto;
	white-space: pre;
}

/* ── Typing indicator ───────────────────────────────────────────── */
.lc-typing-bubble { padding: 11px 14px !important; }

.lc-typing { display: flex; gap: 4px; align-items: center; }

.lc-typing span {
	display: block;
	width: 6px;
	height: 6px;
	border-radius: 50%;
	background: #aaa;
	animation: lc-bounce 1.4s infinite ease-in-out;
}

.lc-typing span:nth-child(1) { animation-delay: -0.32s; }
.lc-typing span:nth-child(2) { animation-delay: -0.16s; }

@keyframes lc-bounce {
	0%, 80%, 100% { transform: scale(0.75); opacity: 0.5; }
	40%            { transform: scale(1);    opacity: 1;   }
}

/* ── Diff viewer ─────────────────────────────────────────────────────── */
.lc-split-diff {
	margin-top: 8px;
	border: 1px solid #e0e0e0;
	border-radius: 6px;
	overflow: hidden;
	width: 100%;
}
.lc-split-header {
	display: grid;
	grid-template-columns: minmax(0, 1fr) 2px minmax(0, 1fr);
	background: #f5f5f5;
	border-bottom: 1px solid #d0d0d0;
}
.lc-split-col-label { padding: 4px 10px; font-weight: 600; font-size: 10px; color: #555; letter-spacing: .04em; text-transform: uppercase; min-width: 0; }
.lc-split-divider-head { background: #d0d0d0; }
.lc-split-body { background: #1c1b1f; max-height: 260px; overflow-y: auto; overflow-x: hidden; }
.lc-split-row {
	display: grid;
	grid-template-columns: minmax(0, 1fr) 2px minmax(0, 1fr);
	border-bottom: 1px solid rgba(255,255,255,.04);
	min-height: 20px;
}
.lc-split-divider { background: #444; }
.lc-split-cell { margin: 0; padding: 2px 10px; font-family: "JetBrains Mono", "Fira Code", monospace; font-size: 11px; line-height: 1.6; color: #e6e1e5; white-space: pre; overflow: hidden; min-width: 0; }
.lc-sdiff-del   { background: rgba(240,80,80,.2);    color: #ff8a8a; }
.lc-sdiff-add   { background: rgba(100,220,100,.18); color: #6ee68e; }
.lc-sdiff-hunk  { background: rgba(144,202,249,.08); color: #90caf9; font-style: italic; }
.lc-sdiff-empty { background: rgba(255,255,255,.03); }

/* ── Tests panel ─────────────────────────────────────────────────────── */
.lc-tests-panel {
	margin-top: 10px;
	border: 1px solid #c8e6c9;
	border-radius: 10px;
	overflow: hidden;
	font-size: 12.5px;
	background: #fff;
}
.lc-tests-header {
	background: #e8f5e9;
	border-bottom: 1px solid #c8e6c9;
	padding: 8px 14px;
	font-weight: 700;
	font-size: 11.5px;
	color: #1b5e20;
	letter-spacing: .02em;
	display: flex;
	align-items: center;
	gap: 6px;
}
.lc-tests-intro {
	padding: 8px 14px 4px;
	font-size: 11.5px;
	color: #666;
	border-bottom: 1px solid #f0f0f0;
}
.lc-tests-checklist { padding: 10px 12px; display: flex; flex-direction: column; gap: 10px; }
.lc-test-item {
	background: #fafafa;
	border: 1px solid #e8e8e8;
	border-radius: 8px;
	padding: 10px 12px;
}
.lc-test-scenario { font-weight: 700; color: #222; margin-bottom: 6px; font-size: 12.5px; }
.lc-test-row { display: flex; gap: 8px; color: #555; margin-top: 3px; line-height: 1.45; }
.lc-test-label {
	flex-shrink: 0;
	font-weight: 700;
	font-size: 10px;
	text-transform: uppercase;
	letter-spacing: .05em;
	color: #4caf50;
	padding-top: 2px;
	min-width: 40px;
}
.lc-test-actions {
	display: flex;
	align-items: center;
	gap: 8px;
	margin-top: 8px;
	flex-wrap: wrap;
}
.lc-run-test-btn {
	padding: 3px 10px;
	font-size: 11px;
	font-weight: 600;
	border: 1px solid #4caf50;
	border-radius: 12px;
	background: #f0faf0;
	color: #2d6a2d;
	cursor: pointer;
	display: flex;
	align-items: center;
	gap: 5px;
	transition: background .15s, opacity .15s;
}
.lc-run-test-btn:hover:not(:disabled) { background: #e0f5e0; }
.lc-run-test-btn:disabled { opacity: .55; cursor: default; }
.lc-test-spinner {
	display: inline-block;
	width: 10px; height: 10px;
	border: 2px solid #4caf50;
	border-top-color: transparent;
	border-radius: 50%;
	animation: lc-spin .7s linear infinite;
}
@keyframes lc-spin { to { transform: rotate(360deg); } }
.lc-test-result { font-size: 11.5px; line-height: 1.4; flex: 1; min-width: 0; }
.lc-test-pass { color: #2d6a2d; }
.lc-test-fail { color: #b33; }


/* ── Action buttons (Apply to Canvas, Clarify) ──────────────────── */
.lc-msg-actions {
	display: flex;
	gap: 6px;
	margin-top: 6px;
	flex-wrap: wrap;
}

.lc-action-btn {
	padding: 4px 12px;
	border-radius: 16px;
	border: 1.5px solid #6c3fe0;
	background: transparent;
	color: #6c3fe0;
	font-size: 12px;
	font-weight: 500;
	cursor: pointer;
	transition: background 0.15s, color 0.15s;
	font-family: inherit;
}

.lc-action-btn:hover { background: linear-gradient(135deg, #6c3fe0 0%, #9b59b6 100%); color: #fff; border-color: transparent; }

.lc-action-btn--reject { border-color: #c62828; color: #c62828; }
.lc-action-btn--reject:hover { background: #c62828; color: #fff; border-color: transparent; }

/* ── Input area ─────────────────────────────────────────────────── */
.lc-input-area {
	background: #fff;
	border-top: 1px solid #eee;
	flex-shrink: 0;
	padding: 6px 12px 10px;
}

.lc-toolbar-row { margin-bottom: 4px; }

.lc-toolbar {
	display: flex;
	align-items: center;
	gap: 2px;
}

.lc-toolbar-btn {
	background: transparent;
	border: 1px solid transparent;
	border-radius: 3px;
	padding: 2px 5px;
	font-size: 12px;
	color: #555;
	cursor: pointer;
	display: flex;
	align-items: center;
	justify-content: center;
	min-width: 22px;
	min-height: 20px;
	transition: background 0.12s, border-color 0.12s;
}

.lc-toolbar-btn:hover { background: #f0f0f0; border-color: #ddd; }


.lc-editor-row {
	display: flex;
	align-items: flex-start;
	gap: 8px;
}

.lc-editor {
	flex: 1;
	border: 1px solid #d1d8dd;
	border-radius: 6px;
	padding: 7px 10px;
	font-size: 13px;
	font-family: inherit;
	min-height: 36px;
	max-height: 90px;
	overflow-y: auto;
	outline: none;
	line-height: 1.5;
	color: #1c1b1f;
	background: #fff;
	transition: border-color 0.15s, box-shadow 0.15s;
	word-break: break-word;
}

.lc-editor:focus { border-color: #80bdff; box-shadow: 0 0 0 .15rem rgba(0,123,255,.18); }
.lc-editor:empty::before { content: attr(data-placeholder); color: #6c757d; pointer-events: none; display: block; }

.lc-send-btn {
	width: 34px;
	height: 34px;
	border-radius: 50%;
	background: linear-gradient(135deg, #6c3fe0 0%, #9b59b6 100%);
	border: none;
	color: #fff;
	display: flex;
	align-items: center;
	justify-content: center;
	cursor: pointer;
	flex-shrink: 0;
	transition: opacity 0.15s, transform 0.1s;
}

.lc-send-btn:hover:not(:disabled)  { opacity: 0.88; transform: scale(1.06); }
.lc-send-btn:active:not(:disabled) { opacity: 0.75; transform: scale(.97); }
.lc-send-btn:disabled { background: #ccc; cursor: not-allowed; }

/* ═══════════════════════════════════════════════════════════════════
   CODE EDITOR PANEL (center)
══════════════════════════════════════════════════════════════════ */
.lc-editor-panel {
	flex: 1;
	display: flex;
	flex-direction: column;
	min-width: 0;
	border-right: 1px solid #eee;
	background: #fafafa;
}

/* ── File bar ───────────────────────────────────────────────────── */
.lc-file-bar {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 8px 14px;
	background: #fff;
	border-bottom: 1px solid #eee;
	flex-shrink: 0;
	gap: 10px;
}

.lc-file-name-area {
	display: flex;
	align-items: center;
	gap: 7px;
	min-width: 0;
	flex: 1;
	color: #555;
}

.lc-filename {
	font-size: 13px;
	font-weight: 500;
	color: #1c1b1f;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
	cursor: text;
}

.lc-filename:hover { text-decoration: underline; }

.lc-name-input {
	flex: 1;
	border: 1px solid #6c3fe0;
	border-radius: 4px;
	padding: 2px 8px;
	font-size: 13px;
	font-weight: 500;
	color: #1c1b1f;
	outline: none;
	background: #fff;
}

.lc-loading-indicator {
	display: flex;
	align-items: center;
	gap: 6px;
	font-size: 12px;
	color: #888;
}

.lc-file-actions {
	display: flex;
	align-items: center;
	gap: 6px;
	flex-shrink: 0;
}

.lc-file-btn {
	display: flex;
	align-items: center;
	gap: 5px;
	border: 1px solid #e0e0e0;
	border-radius: 5px;
	background: #fff;
	color: #555;
	font-size: 12px;
	padding: 4px 10px;
	cursor: pointer;
	transition: background 0.15s, border-color 0.15s;
	font-family: inherit;
}

.lc-file-btn:hover { background: #f5f5f5; border-color: #ccc; }
.lc-file-btn--active { background: #f0ebff; border-color: #6c3fe0; color: #6c3fe0; }

/* ── Save status in file bar ────────────────────────────────────────── */
.lc-save-status {
	font-size: 11px;
	display: flex;
	align-items: center;
	gap: 4px;
	white-space: nowrap;
}
.lc-unsaved   { color: #e65100; }
.lc-saved     { color: #2e7d32; }
.lc-autosaving { color: #888; }

/* ── Script browser ─────────────────────────────────────────────────── */
.lc-script-browser-wrap {
	position: relative;
}

.lc-script-dropdown {
	position: absolute;
	right: 0;
	top: calc(100% + 6px);
	z-index: 250;
	width: 260px;
	background: #fff;
	border: 1px solid #ddd;
	border-radius: 8px;
	box-shadow: 0 6px 20px rgba(0,0,0,.12);
	display: flex;
	flex-direction: column;
	overflow: hidden;
}

.lc-script-dropdown-header {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 8px 12px;
	font-size: 11px;
	font-weight: 700;
	color: #555;
	text-transform: uppercase;
	letter-spacing: 0.04em;
	border-bottom: 1px solid #eee;
	background: #fafafa;
}

.lc-script-dropdown-search {
	padding: 6px 8px;
	border-bottom: 1px solid #eee;
}

.lc-script-search-input {
	width: 100%;
	border: 1px solid #ddd;
	border-radius: 5px;
	padding: 4px 8px;
	font-size: 12px;
	outline: none;
	color: #1c1b1f;
	background: #fff;
	box-sizing: border-box;
}

.lc-script-search-input:focus { border-color: #6c3fe0; box-shadow: 0 0 0 2px rgba(108,63,224,.1); }

.lc-script-dropdown-list {
	max-height: 220px;
	overflow-y: auto;
}

.lc-script-dropdown-empty {
	padding: 16px 12px;
	text-align: center;
	font-size: 12px;
	color: #aaa;
}

.lc-script-dropdown-item {
	display: flex;
	align-items: center;
	gap: 8px;
	padding: 7px 12px;
	cursor: pointer;
	transition: background 0.12s;
	border-bottom: 1px solid #f5f5f5;
}

.lc-script-dropdown-item:last-child { border-bottom: none; }
.lc-script-dropdown-item:hover { background: #f5f0ff; }
.lc-script-dropdown-item--active { background: #f0ebff; }

.lc-script-item-icon { flex-shrink: 0; color: #888; }
.lc-script-item-check { flex-shrink: 0; color: #6c3fe0; margin-left: auto; }

.lc-script-item-info {
	flex: 1;
	min-width: 0;
}

.lc-script-item-name {
	font-size: 12px;
	font-weight: 500;
	color: #1c1b1f;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.lc-script-item-type {
	font-size: 10px;
	color: #888;
	margin-top: 1px;
}

/* ── Script Settings Panel ──────────────────────────────────────── */
.lc-settings-panel {
	background: #fafafa;
	border-bottom: 1px solid #e8e8e8;
	padding: 10px 14px;
	flex-shrink: 0;
}
.lc-settings-grid {
	display: flex;
	flex-wrap: wrap;
	gap: 10px 16px;
	align-items: flex-end;
}
.lc-settings-field {
	display: flex;
	flex-direction: column;
	gap: 3px;
	min-width: 140px;
	flex: 1 1 140px;
	max-width: 220px;
}
.lc-settings-field--inline {
	flex-direction: row;
	align-items: center;
	gap: 8px;
	min-width: auto;
	flex: 0 0 auto;
}
.lc-settings-label {
	font-size: 10px;
	font-weight: 600;
	color: #666;
	text-transform: uppercase;
	letter-spacing: 0.04em;
}
.lc-settings-input,
.lc-settings-select {
	height: 28px;
	padding: 0 8px;
	font-size: 12px;
	border: 1px solid #ddd;
	border-radius: 6px;
	background: #fff;
	color: #1c1b1f;
	outline: none;
	width: 100%;
}
.lc-settings-input:focus,
.lc-settings-select:focus { border-color: #6c3fe0; box-shadow: 0 0 0 2px rgba(108,63,224,.1); }
.lc-dropdown-backdrop {
	position: fixed;
	inset: 0;
	z-index: 199;
}
.lc-settings-dropdown-wrap { position: relative; }
.lc-settings-dropdown {
	position: absolute;
	z-index: 200;
	top: 100%;
	left: 0;
	right: 0;
	max-height: 160px;
	overflow-y: auto;
	background: #fff;
	border: 1px solid #ddd;
	border-radius: 6px;
	box-shadow: 0 4px 12px rgba(0,0,0,.1);
	margin-top: 2px;
}
.lc-settings-dropdown-item {
	padding: 5px 10px;
	font-size: 12px;
	cursor: pointer;
	color: #1c1b1f;
}
.lc-settings-dropdown-item:hover { background: #f0ebff; color: #6c3fe0; }
.lc-settings-checkbox { width: 14px; height: 14px; accent-color: #6c3fe0; cursor: pointer; }

.lc-settings-slide-enter-active,
.lc-settings-slide-leave-active { transition: max-height 0.2s ease, opacity 0.2s ease; max-height: 200px; overflow: hidden; }
.lc-settings-slide-enter-from,
.lc-settings-slide-leave-to { max-height: 0; opacity: 0; }

/* ── Code area ──────────────────────────────────────────────────── */
.lc-code-area {
	flex: 1;
	display: flex;
	overflow: hidden;
	background: #fafafa;
}

.lc-line-numbers {
	width: 40px;
	flex-shrink: 0;
	background: #f0f0f0;
	border-right: 1px solid #e0e0e0;
	padding: 14px 0;
	overflow: hidden;
	user-select: none;
	font-family: "JetBrains Mono", "Fira Code", monospace;
	font-size: 12.5px;
	line-height: 1.55;
}

.lc-line-num {
	text-align: right;
	padding-right: 8px;
	color: #999;
	line-height: 1.55;
	font-size: 12px;
}

.lc-code-textarea {
	flex: 1;
	border: none;
	outline: none;
	resize: none;
	padding: 14px 16px;
	font-family: "JetBrains Mono", "Fira Code", monospace;
	font-size: 12.5px;
	line-height: 1.55;
	background: #fafafa;
	color: #1c1b1f;
	tab-size: 4;
	white-space: pre;
	overflow-x: auto;
}

.lc-code-textarea::placeholder { color: #bbb; }


/* ── Spinners ───────────────────────────────────────────────────── */
.lc-spinner-sm {
	width: 12px;
	height: 12px;
	border: 2px solid #ddd;
	border-top-color: #666;
	border-radius: 50%;
	animation: lc-spin 0.7s linear infinite;
	display: inline-block;
}

.lc-spinner-white { border-color: rgba(255,255,255,.4); border-top-color: #fff; }

@keyframes lc-spin { to { transform: rotate(360deg); } }

/* ═══════════════════════════════════════════════════════════════════
   VERSION HISTORY PANEL (right, slides in)
══════════════════════════════════════════════════════════════════ */
.lc-version-panel {
	width: 240px;
	flex-shrink: 0;
	background: #fff;
	border-left: 1px solid #eee;
	display: flex;
	flex-direction: column;
	overflow: hidden;
}

.lc-version-panel-header {
	padding: 10px 14px;
	font-size: 13px;
	font-weight: 600;
	color: #1c1b1f;
	border-bottom: 1px solid #eee;
	flex-shrink: 0;
	display: flex;
	align-items: center;
	justify-content: space-between;
}

.lc-ver-refresh-btn {
	width: 26px;
	height: 26px;
	border-radius: 50%;
	border: none;
	background: transparent;
	color: #6c3fe0;
	cursor: pointer;
	display: flex;
	align-items: center;
	justify-content: center;
	transition: background 0.15s;
}
.lc-ver-refresh-btn:hover { background: rgba(108, 63, 224, 0.1); }
.lc-ver-refresh-btn:disabled { opacity: 0.4; cursor: default; }

.lc-ver-spinner {
	width: 22px;
	height: 22px;
	border: 2.5px solid #e0d6f7;
	border-top-color: #6c3fe0;
	border-radius: 50%;
	animation: lc-spin 0.7s linear infinite;
}

.lc-spin {
	animation: lc-spin 0.7s linear infinite;
}

.lc-version-panel > .lc-version-empty,
.lc-version-panel > .lc-version-item {
	overflow-y: auto;
}

/* Make the items scrollable */
.lc-version-panel {
	overflow-y: auto;
}

/* ── Empty state ────────────────────────────────────────────────── */
.lc-version-empty {
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	padding: 30px 20px;
	text-align: center;
	color: #aaa;
	gap: 8px;
	font-size: 12px;
}

.lc-version-empty p { margin: 0; }
.lc-version-empty-sub { font-size: 11px; color: #bbb; }

/* ── Version item ───────────────────────────────────────────────── */
.lc-version-item {
	padding: 10px 14px;
	border-bottom: 1px solid #f0f0f0;
	cursor: default;
	transition: background 0.12s;
}

.lc-version-item:hover { background: #fafafa; }

.lc-version-active {
	border-left: 3px solid #6c3fe0;
	background: #f5f0ff;
}

.lc-version-top {
	display: flex;
	align-items: center;
	justify-content: space-between;
	margin-bottom: 3px;
}

.lc-version-top-left {
	display: flex;
	align-items: center;
	gap: 5px;
}

.lc-version-num {
	font-size: 12px;
	font-weight: 600;
	color: #1c1b1f;
}

.lc-active-badge {
	background: linear-gradient(135deg, #6c3fe0 0%, #9b59b6 100%);
	color: #fff;
	font-size: 10px;
	font-weight: 600;
	border-radius: 100px;
	padding: 1px 7px;
}

.lc-version-time {
	font-size: 11px;
	color: #888;
}

.lc-version-author {
	font-size: 12px;
	font-weight: 500;
	color: #333;
	margin-bottom: 2px;
}

.lc-version-desc {
	font-size: 11px;
	color: #666;
	margin-bottom: 4px;
}

.lc-version-links {
	display: flex;
	gap: 6px;
}

.lc-ver-link {
	background: none;
	border: none;
	padding: 0;
	font-size: 11px;
	color: #6c3fe0;
	cursor: pointer;
	font-family: inherit;
	text-decoration: underline;
}

.lc-ver-link:hover { color: #5430b0; }

/* ── Inline diff (inside version panel) ────────────────────────── */
.lc-inline-diff {
	margin-top: 8px;
	border: 1px solid #e0e0e0;
	border-radius: 5px;
	overflow: hidden;
}

.lc-inline-diff-header {
	display: flex;
	background: #f5f5f5;
	border-bottom: 1px solid #e0e0e0;
}

.lc-inline-diff-header span {
	flex: 1;
	padding: 3px 8px;
	font-size: 10px;
	font-weight: 600;
	color: #666;
}

.lc-inline-diff-header span:first-child { border-right: 1px solid #e0e0e0; }

.lc-inline-diff-body {
	background: #1c1b1f;
	max-height: 180px;
	overflow-y: auto;
}

.lc-diff-row {
	display: flex;
	border-bottom: 1px solid rgba(255,255,255,.04);
	min-height: 16px;
}

.lc-diff-cell {
	flex: 1;
	margin: 0;
	padding: 1px 6px;
	font-family: monospace;
	font-size: 10px;
	line-height: 1.5;
	color: #e6e1e5;
	white-space: pre-wrap;
	overflow: hidden;
	min-width: 0;
	border-right: 1px solid rgba(255,255,255,.08);
}

.lc-diff-cell:last-child { border-right: none; }

/* ── Slide transition ───────────────────────────────────────────── */
.lc-slide-in-enter-active,
.lc-slide-in-leave-active {
	transition: width 0.22s ease, opacity 0.18s ease;
	overflow: hidden;
}

.lc-slide-in-enter-from,
.lc-slide-in-leave-to {
	width: 0;
	opacity: 0;
}
</style>
