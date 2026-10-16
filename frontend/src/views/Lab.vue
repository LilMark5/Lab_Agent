<template>
  <div>
    <el-card>
      <template #header>
        <div style="font-weight: bold">实验室管理</div>
      </template>
      <div style="margin-bottom: 12px">
        <el-input
          v-model="params.keywords"
          placeholder="请输入名称或位置查询"
          style="width: 240px; margin-right: 8px"
          clearable
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        />
        <el-button type="primary" :icon="Search" @click="handleSearch">查询</el-button>
        <el-button type="success" :icon="Plus" @click="handleCreate">新增</el-button>
      </div>

      <el-table :data="tableData" v-loading="loading" style="width: 100%">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="location" label="位置" />
        <el-table-column prop="capacity" label="容量" width="80" />
        <el-table-column label="开放时间">
          <template #default="{ row }">
            {{ row.open_time && row.close_time ? `${row.open_time} - ${row.close_time}` : '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="description" label="简介" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 1 ? 'success' : 'danger'">
              {{ row.status === 1 ? '开放' : '关闭' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button type="primary" text bg @click="handleEdit(row)">编辑</el-button>
            <el-button type="danger" text bg @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div style="margin-top: 12px; display: flex; justify-content: flex-end">
        <el-pagination
          v-model:current-page="params.page"
          v-model:page-size="params.pageSize"
          :total="total"
          background
          layout="total, prev, pager, next"
          @current-change="load"
        />
      </div>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="form.id ? '编辑实验室' : '新增实验室'" width="520px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="位置">
          <el-input v-model="form.location" />
        </el-form-item>
        <el-form-item label="容纳人数">
          <el-input-number v-model="form.capacity" :min="0" />
        </el-form-item>
        <el-form-item label="开放时间">
          <el-time-picker
            v-model="form.open_time"
            value-format="HH:mm"
            format="HH:mm"
            placeholder="开始时间"
          />
        </el-form-item>
        <el-form-item label="关闭时间">
          <el-time-picker
            v-model="form.close_time"
            value-format="HH:mm"
            format="HH:mm"
            placeholder="结束时间"
          />
        </el-form-item>
        <el-form-item label="简介">
          <el-input v-model="form.description" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="状态">
          <el-radio-group v-model="form.status">
            <el-radio :value="1">开放</el-radio>
            <el-radio :value="0">关闭</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="formLoading" @click="handleSave">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'

import { createLabApi, deleteLabApi, getLabPageList, updateLabApi } from '@/api/lab'

const params = reactive({ page: 1, pageSize: 10, keywords: '' })
const loading = ref(false)
const tableData = ref([])
const total = ref(0)
const dialogVisible = ref(false)
const formLoading = ref(false)
const formRef = ref()
const form = reactive({
  id: null,
  name: '',
  location: '',
  capacity: 0,
  open_time: '',
  close_time: '',
  description: '',
  status: 1
})

const rules = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }]
}

const resetForm = () => {
  Object.assign(form, {
    id: null,
    name: '',
    location: '',
    capacity: 0,
    open_time: '',
    close_time: '',
    description: '',
    status: 1
  })
}

const load = async () => {
  loading.value = true
  try {
    const res = await getLabPageList({
      page: params.page,
      page_size: params.pageSize,
      keywords: params.keywords
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

const handleCreate = () => {
  resetForm()
  dialogVisible.value = true
}

const handleEdit = (row) => {
  resetForm()
  Object.assign(form, row)
  dialogVisible.value = true
}

const handleDelete = (row) => {
  ElMessageBox.confirm(`确认删除实验室 [${row.name}] ？`, '确认删除', {
    type: 'warning'
  }).then(async () => {
    const res = await deleteLabApi(row.id)
    if (res.code === 200) {
      ElMessage.success('删除成功')
      load()
    }
  })
}

const handleSave = async () => {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  formLoading.value = true
  try {
    const payload = {
      name: form.name,
      location: form.location,
      capacity: form.capacity,
      open_time: form.open_time,
      close_time: form.close_time,
      description: form.description,
      status: form.status
    }
    const res = form.id
      ? await updateLabApi(form.id, payload)
      : await createLabApi(payload)
    if (res.code === 200) {
      dialogVisible.value = false
      ElMessage.success('操作成功')
      load()
    }
  } finally {
    formLoading.value = false
  }
}

onMounted(load)
</script>
