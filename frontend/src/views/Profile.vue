<template>
  <el-card style="max-width: 640px">
    <template #header>
      <div style="font-weight: bold">个人信息</div>
    </template>
    <el-form ref="formRef" :model="form" :rules="rules" label-width="80px" v-loading="loading">
      <el-form-item label="头像">
        <el-upload :http-request="handleFileUpload" :show-file-list="false">
          <img v-if="form.avatar" :src="form.avatar" class="avatar" alt="" />
          <el-icon v-else class="avatar-uploader-icon"><Plus /></el-icon>
        </el-upload>
      </el-form-item>
      <el-form-item label="账号">
        <el-input v-model="form.username" disabled />
      </el-form-item>
      <el-form-item label="姓名" prop="name">
        <el-input v-model="form.name" />
      </el-form-item>
      <el-form-item label="角色">
        <el-input :model-value="roleLabel" disabled />
      </el-form-item>
      <el-form-item label="邮箱" prop="email">
        <el-input v-model="form.email" />
      </el-form-item>
      <el-form-item label="手机号" prop="phone">
        <el-input v-model="form.phone" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">保存修改</el-button>
      </el-form-item>
    </el-form>
  </el-card>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { uploadFileApi } from '@/api/file'
import { getUserInfoApi, updateUserInfoApi } from '@/api/user'
import { useUser } from '@/utils/user'

const { updateUser } = useUser()
const loading = ref(false)
const submitting = ref(false)
const formRef = ref()
const form = reactive({ username: '', name: '', role: '', email: '', phone: '', avatar: '' })

const roleLabel = computed(() => {
  return form.role === 'admin' ? '管理员' : form.role === 'student' ? '学生' : '未知角色'
})

const rules = {
  name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  email: [{ type: 'email', message: '邮箱格式错误', trigger: 'blur' }],
  phone: [{ pattern: /^1[3-9]\d{9}$/, message: '手机号格式错误', trigger: 'blur' }]
}

const handleFileUpload = async ({ file }) => {
  try {
    const res = await uploadFileApi(file)
    if (res.code === 200) form.avatar = res.data?.url
  } catch {
    // 上传失败已由 request 统一提示。
  }
}

const loadUserInfo = async () => {
  loading.value = true
  try {
    const res = await getUserInfoApi()
    if (res.code === 200) Object.assign(form, res.data)
  } finally {
    loading.value = false
  }
}

const handleSubmit = async () => {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    const res = await updateUserInfoApi({
      name: form.name,
      email: form.email,
      phone: form.phone,
      avatar: form.avatar
    })
    if (res.code === 200) {
      updateUser(res.data)
      ElMessage.success('更新成功')
    }
  } finally {
    submitting.value = false
  }
}

onMounted(loadUserInfo)
</script>

<style scoped>
.avatar {
  width: 120px;
  height: 120px;
  border-radius: 6px;
  object-fit: cover;
}
.avatar-uploader-icon {
  font-size: 28px;
  color: #8c939d;
  width: 120px;
  height: 120px;
  text-align: center;
}
</style>
