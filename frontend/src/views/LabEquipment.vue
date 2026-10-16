<template>
  <div>
    <el-card>
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <div style="font-weight: bold">{{ lab?.name || '实验室' }}设备列表</div>
          <div>
            <el-button type="primary" @click="openLabReserve">预约实验室</el-button>
            <el-button @click="router.push('/manager/lablist')">返回实验室列表</el-button>
          </div>
        </div>
      </template>

      <div v-if="lab" class="lab-intro">
        <div style="margin-bottom: 8px">简介：{{ lab.description || '-' }}</div>
        <div>
          位置：{{ lab.location || '-' }}
          <span style="margin: 0 10px">|</span>容纳 {{ lab.capacity }} 人
          <span style="margin: 0 10px">|</span>
          开放：{{ lab.open_time && lab.close_time ? `${lab.open_time} - ${lab.close_time}` : '-' }}
        </div>
      </div>

      <el-table :data="tableData" v-loading="loading" style="width: 100%">
        <el-table-column prop="name" label="设备名称" />
        <el-table-column prop="spec" label="型号规格" />
        <el-table-column prop="quantity" label="数量" width="80" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 1 ? 'success' : 'danger'">
              {{ row.status === 1 ? '正常' : '维修' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button
              :disabled="row.status !== 1"
              type="primary"
              text
              bg
              @click="openEquipmentReserve(row)"
            >
              预约
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div style="margin-top: 12px; display: flex; justify-content: flex-end">
        <el-pagination
          v-model:current-page="params.page"
          v-model:page-size="params.page_size"
          :total="total"
          background
          layout="total, prev, pager, next"
          @current-change="loadEquipment"
        />
      </div>
    </el-card>

    <ReserveDialog
      v-model:visible="reserveVisible"
      :lab-id="lab?.id"
      :lab-name="lab?.name"
      :equipment-id="currentEquipment?.id"
      :equipment-name="currentEquipment?.name"
    />
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import { getEquipmentPageList } from '@/api/equipment'
import { getLab } from '@/api/lab'
import ReserveDialog from '@/components/ReserveDialog.vue'

const route = useRoute()
const router = useRouter()
const lab = ref(null)
const params = reactive({
  page: 1,
  page_size: 10,
  lab_id: Number(route.query.lab_id)
})
const loading = ref(false)
const tableData = ref([])
const total = ref(0)
const reserveVisible = ref(false)
const currentEquipment = ref(null)

const loadLab = async () => {
  if (!params.lab_id) {
    ElMessage.error('缺少实验室查询条件 [lab_id]')
    return
  }
  const res = await getLab(params.lab_id)
  if (res.code === 200) lab.value = res.data
}

const loadEquipment = async () => {
  loading.value = true
  try {
    const res = await getEquipmentPageList(params)
    if (res.code === 200) {
      tableData.value = res.data?.list
      total.value = res.data?.total
    }
  } finally {
    loading.value = false
  }
}

const openLabReserve = () => {
  currentEquipment.value = null
  reserveVisible.value = true
}

const openEquipmentReserve = (row) => {
  currentEquipment.value = row
  reserveVisible.value = true
}

onMounted(() => {
  loadLab()
  loadEquipment()
})
</script>

<style scoped>
.lab-intro {
  color: #666;
  margin-bottom: 16px;
  background-color: #f4f5ff;
  padding: 10px;
  border-radius: 6px;
}
</style>
