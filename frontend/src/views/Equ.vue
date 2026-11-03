<template>
  <div>
    <el-card>
      <template #header>
        <div style="font-weight: bold">设备管理</div>
      </template>
      <div style="margin-bottom: 12px">
        <el-input
          v-model="params.keywords"
          placeholder="请输入设备名称查询"
          style="width: 200px; margin-right: 8px"
          clearable
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        />
        <el-select
          v-model="params.lab_id"
          placeholder="按实验室筛选"
          clearable
          style="width: 200px; margin-right: 8px"
          @change="handleSearch"
        >
          <el-option v-for="lab in labOptions" :key="lab.id" :label="lab.name" :value="lab.id" />
        </el-select>
        <el-button type="primary" :icon="Search" @click="handleSearch">查询</el-button>
        <el-button type="success" :icon="Plus" @click="handleCreate">新增</el-button>
      </div>

      <el-table :data="tableData" v-loading="loading" style="width: 100%">
        <el-table-column prop="name" label="设备名称" />
        <el-table-column prop="lab_name" label="所属实验室" />
        <el-table-column prop="spec" label="型号规格" />
        <el-table-column prop="quantity" label="数量" width="80" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 1 ? 'success' : 'danger'">
              {{ row.status === 1 ? '正常' : '维修' }}
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

    <el-dialog v-model="dialogVisible" :title="form.id ? '编辑设备' : '新增设备'" width="520px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="所属实验室" prop="lab_id">
          <el-select v-model="form.lab_id" placeholder="请选择实验室">
            <el-option v-for="lab in labOptions" :key="lab.id" :label="lab.name" :value="lab.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="设备名称" prop="name">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="型号规格">
          <el-input v-model="form.spec" />
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="form.quantity" :min="1" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="form.description" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="状态">
          <el-radio-group v-model="form.status">
            <el-radio :value="1">正常</el-radio>
            <el-radio :value="0">维修</el-radio>
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

import {
  createEquipmentApi,
  deleteEquipmentApi,
  getEquipmentPageList,
  updateEquipmentApi
} from '@/api/equipment'
import { getLabPageList } from '@/api/lab'

const params = reactive({ page: 1, pageSize: 10, keywords: '', lab_id: null })
const loading = ref(false)
const tableData = ref([])
const total = ref(0)
const labOptions = ref([])
const dialogVisible = ref(false)
const formLoading = ref(false)
const formRef = ref()
const form = reactive({
  id: null,
  lab_id: null,
  name: '',
  spec: '',
  quantity: 1,
  description: '',
  status: 1
})

const rules = {
  lab_id: [{ required: true, message: '请选择实验室', trigger: 'change' }],
  name: [{ required: true, message: '请输入设备名称', trigger: 'blur' }]
}

const loadLabOptions = async () => {
  const res = await getLabPageList({ page: 1, page_size: 100 })
  if (res.code === 200) labOptions.value = res.data?.list || []
}

const resetForm = () => {
  Object.assign(form, {
    id: null,
    lab_id: null,
    name: '',
    spec: '',
    quantity: 1,
    description: '',
    status: 1
  })
}

const load = async () => {
  loading.value = true
  try {
    const res = await getEquipmentPageList({
      page: params.page,
      page_size: params.pageSize,
      keywords: params.keywords,
      lab_id: params.lab_id || undefined
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
  ElMessageBox.confirm(`确认删除设备 [${row.name}] ？`, '确认删除', {
    type: 'warning'
  }).then(async () => {
    const res = await deleteEquipmentApi(row.id)
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
      lab_id: form.lab_id,
      name: form.name,
      spec: form.spec,
      quantity: form.quantity,
      description: form.description,
      status: form.status
    }
    const res = form.id
      ? await updateEquipmentApi(form.id, payload)
      : await createEquipmentApi(payload)
    if (res.code === 200) {
      dialogVisible.value = false
      ElMessage.success('操作成功')
      load()
    }
  } finally {
    formLoading.value = false
  }
}

onMounted(() => {
  loadLabOptions()
  load()
})
</script>
