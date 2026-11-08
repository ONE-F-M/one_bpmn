<template>
	<div v-if="activeTab" class="fb-form">
		<div v-if="openMenu" class="fb-menu-backdrop" @click="openMenu = null"></div>
		<div class="fb-tab-header">
			<draggable
				v-if="tabs.length > 1"
				:list="tabs"
				item-key="id"
				class="fb-tabs"
				:animation="150"
			>
				<template #item="{ element: tab, index }">
					<div
						class="fb-tab"
						:class="{ active: index === activeTabIndex }"
						@click="activeTabIndex = index"
						@dblclick="selectContainer('tab', tab)"
					>
						<span>{{ tabLabel(tab, index) }}</span>
						<button
							v-if="tabs.length > 1"
							class="fb-tab-x"
							title="Remove tab"
							@click.stop="removeTab(tab)"
						>
							✕
						</button>
					</div>
				</template>
			</draggable>
			<div class="fb-tab-actions">
				<button class="fb-addtab" title="Add tab" @click="addTab()">+ Add tab</button>
			</div>
		</div>

		<div class="fb-canvas">
			<draggable
				:list="activeTab.sections"
				item-key="id"
				group="fb-sections"
				handle=".fb-section-grip"
				:animation="200"
			>
				<template #item="{ element: section }">
					<div class="fb-section-container">
						<div
							class="fb-section"
							:class="{ selected: isSel('section', section) }"
							@click.self="selectContainer('section', section)"
						>
							<div
								class="fb-section-header"
								@click.stop="selectContainer('section', section)"
							>
								<div class="fb-section-label">
									<span class="fb-section-grip" title="Drag to reorder">⠿</span>
									<span
										class="fb-section-title"
										:class="{ empty: !(section.df && section.df.label) }"
										>{{ (section.df && section.df.label) || "No Label" }}</span
									>
								</div>
								<div class="fb-menu-wrap">
									<button
										class="fb-menu-btn"
										title="Section options"
										@click.stop="toggleMenu(section)"
									>
										⋯
									</button>
									<div v-if="openMenu === section" class="fb-menu" @click.stop>
										<div
											v-for="(g, gi) in sectionMenu(section)"
											:key="gi"
											class="fb-menu-group"
										>
											<div class="fb-menu-title">{{ g.group }}</div>
											<button
												v-for="it in g.items"
												:key="it.label"
												class="fb-menu-item"
												@click.stop="it.onClick()"
											>
												{{ it.label }}
											</button>
										</div>
									</div>
								</div>
							</div>
							<draggable
								:list="section.columns"
								item-key="id"
								group="fb-columns"
								class="fb-section-columns"
								:animation="200"
							>
								<template #item="{ element: column }">
									<div
										class="fb-column"
										:class="{ selected: isSel('column', column) }"
										@click.self="selectContainer('column', column)"
									>
										<draggable
											:list="column.fields"
											item-key="id"
											group="fb-fields"
											class="fb-column-container"
											:animation="200"
										>
											<template #item="{ element: fld }">
												<DocuFieldCard :fld="fld" :column="column" />
											</template>
										</draggable>
										<div class="fb-add-field">
											<button
												class="fb-add-btn"
												@click.stop="addFieldToColumn(column)"
											>
												+ Add field
											</button>
										</div>
									</div>
								</template>
							</draggable>
						</div>
					</div>
				</template>
			</draggable>
		</div>
	</div>
</template>

<script setup>
import draggable from "vuedraggable";
import DocuFieldCard from "@/components/Docu/DocuFieldCard.vue";
import { useDocu } from "@/composables/useDocu";

const {
	openMenu,
	tabs,
	activeTabIndex,
	activeTab,
	selectContainer,
	isSel,
	tabLabel,
	addFieldToColumn,
	addTab,
	removeTab,
	toggleMenu,
	sectionMenu,
} = useDocu();
</script>

<style scoped src="@/components/Docu/docuFormCanvas.css"></style>
