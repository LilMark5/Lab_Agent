<template>
  <div>
    <el-card>
      <template #header>
        <div style="font-weight: bold">实验室列表</div>
      </template>
      <div style="margin-bottom: 12px">
        <el-input
          v-model="params.keywords"
          placeholder="请输入名称查询"
          style="width: 240px; margin-right: 8px"
          clearable
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        />
        <el-button type="primary" :icon="Search" @click="handleSearch">查询</el-button>
      </div>

      <el-row :gutter="16" v-loading="loading">
        <el-col v-for="item in tableData" :key="item.id" :span="6" style="margin-bottom: 16px">
          <el-card shadow="hover">
            <img
              v-if="item.img"
              :src="item.img"
              alt=""
              class="lab-cover"
            />
            <div v-else class="lab-cover placeholder"></div>
            <div style="font-size: 16px; font-weight: bold; margin-top: 10px">{{ item.name }}</div>
            <div class="info">位置：{{ item.location || '-' }}</div>
            <div class="info">容量：{{ item.capacity }} 人</div>
            <div class="info">
              开放：{{ item.open_time && item.close_time ? `${item.open_time} - ${item.close_time}` : '-' }}
            </div>
            <div style="margin-top: 12px; display: flex; gap: 8px">
              <el-button style="flex: 1" @click="handleViewEquipment(item)">查看设备</el-button>
              <el-button style="flex: 1" type="primary" @click="handleReserve(item)">预约</el-button>
            </div>
          </el-card>
        </el-col>
      </el-row>

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

    <ReserveDialog
      v-model:visible="reserveVisible"
      :lab-id="currentLab?.id"
      :lab-name="currentLab?.name"
    />
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Search } from '@element-plus/icons-vue'

import { getLabPageList } from '@/api/lab'
import ReserveDialog from '@/components/ReserveDialog.vue'

const router = useRouter()
const params = reactive({ page: 1, page_size: 8, keywords: '', status: 1 })
const loading = ref(false)
const tableData = ref([])
const total = ref(0)
const reserveVisible = ref(false)
const currentLab = ref(null)

const load = async () => {
  loading.value = true
  try {
    const res = await getLabPageList(params)
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

const handleViewEquipment = (lab) => {
  router.push({ path: '/manager/lab-equipment', query: { lab_id: lab.id } })
}

const handleReserve = (lab) => {
  currentLab.value = lab
  reserveVisible.value = true
}

onMounted(load)
</script>

<style scoped>
.lab-cover {
  width: 100%;
  height: 150px;
  object-fit: cover;
  border-radius: 6px;
}
.placeholder {
  background-color: #f5f7fa;
}
.info {
  font-size: 13px;
  margin-top: 6px;
  color: #666;
}
</style>
