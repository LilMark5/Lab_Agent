<template>
  <div>
    <el-card>
      <template #header>
        <div style="font-weight: bold">预约审核</div>
      </template>
      <div style="margin-bottom: 12px">
        <el-select
          v-model="params.status"
          placeholder="请选择状态"
          clearable
          style="width: 200px; margin-right: 8px"
          @change="handleSearch"
        >
          <el-option :value="0" label="待审核" />
          <el-option :value="1" label="已通过" />
          <el-option :value="2" label="已拒绝" />
          <el-option :value="3" label="已取消" />
        </el-select>
        <el-button type="primary" @click="handleSearch">查询</el-button>
      </div>

      <el-table :data="tableData" v-loading="loading" style="width: 100%">
        <el-table-column prop="lab_name" label="实验室" />
        <el-table-column label="类型">
          <template #default="{ row }">
            <el-tag :type="row.type === '实验室' ? 'success' : 'primary'">{{ row.type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="设备">
          <template #default="{ row }">{{ row.equipment_name || '-' }}</template>
        </el-table-column>
        <el-table-column prop="date" label="日期" />
        <el-table-column label="时段">
          <template #default="{ row }">{{ row.start_time }} - {{ row.end_time }}</template>
        </el-table-column>
        <el-table-column prop="user_name" label="预约人" width="100" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <template v-if="row.status === 0">
              <el-button type="success" text bg @click="handleAudit(row, 1)">通过</el-button>
              <el-button type="danger" text bg @click="handleAudit(row, 2)">拒绝</el-button>
            </template>
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
          @current-change="load"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { auditReservationApi, getReservationPageList } from '@/api/reservation'

const params = reactive({ page: 1, page_size: 10, status: 0 })
const loading = ref(false)
const tableData = ref([])
const total = ref(0)

const statusType = (status) => ({ 0: 'warning', 1: 'success', 2: 'danger', 3: 'info' }[status] || 'info')
const statusText = (status) => ({ 0: '待审核', 1: '已通过', 2: '已拒绝', 3: '已取消' }[status] || '-')

const load = async () => {
  loading.value = true
  try {
    const res = await getReservationPageList({
      page: params.page,
      page_size: params.page_size,
      status: params.status ?? undefined
    })
    if (res.code === 200) {
      tableData.value = res.data?.list
      total.value = res.data?.total
    }
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  params.page = 1
  load()
}

const handleAudit = (row, status) => {
  const action = status === 1 ? '通过' : '拒绝'
  ElMessageBox.confirm(`${action} [${row.user_name}] 的预约？`, '审核', {
    type: 'warning'
  }).then(async () => {
    const res = await auditReservationApi(row.id, status)
    if (res.code === 200) {
      ElMessage.success(`审核${action}`)
      load()
    }
  })
}

onMounted(load)
</script>
