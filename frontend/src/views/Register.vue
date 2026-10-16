<template>
  <div class="register-container">
    <div class="register-box">
      <h1>欢迎注册</h1>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="0px">
        <el-form-item prop="username">
          <el-input
            v-model="form.username"
            size="large"
            placeholder="请输入账号"
            :prefix-icon="User"
          />
        </el-form-item>
        <el-form-item prop="name">
          <el-input
            v-model="form.name"
            size="large"
            placeholder="请输入姓名（可选）"
            :prefix-icon="UserFilled"
          />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            size="large"
            placeholder="请输入密码"
            :prefix-icon="Lock"
            show-password
          />
        </el-form-item>
        <el-form-item prop="confirmPassword">
          <el-input
            v-model="form.confirmPassword"
            type="password"
            size="large"
            placeholder="请确认密码"
            :prefix-icon="Lock"
            show-password
          />
        </el-form-item>
        <el-button
          type="primary"
          size="large"
          style="width: 100%"
          :loading="loading"
          @click="register"
        >
          注 册
        </el-button>
        <div class="login-link">
          已有账号？<router-link to="/login">去登录</router-link>
        </div>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { User, UserFilled, Lock } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'

import { registerApi } from '@/api/auth'

const router = useRouter()
const formRef = ref()
const loading = ref(false)
const form = reactive({ username: '', name: '', password: '', confirmPassword: '' })

const validatePass = (rule, value, callback) => {
  if (!value) callback(new Error('请确认密码'))
  else if (value !== form.password) callback(new Error('两次密码输入不一致'))
  else callback()
}

const rules = {
  username: [{ required: true, message: '请输入账号', trigger: 'blur' }],
  password: [{ required: true, min: 3, message: '密码至少 3 位', trigger: 'blur' }],
  confirmPassword: [{ validator: validatePass, trigger: 'blur' }]
}

const register = async () => {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    const res = await registerApi({
      username: form.username,
      name: form.name || form.username,
      password: form.password
    })
    if (res.code === 200) {
      ElMessage.success('注册成功')
      await router.push('/login')
    }
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.register-container {
  height: 100vh;
  display: flex;
  justify-content: center;
  align-items: center;
  background: linear-gradient(135deg, #e0f0ff 0%, #f5f7fa 100%);
}
.register-box {
  width: 400px;
  padding: 36px 32px;
  border-radius: 10px;
  background: white;
  box-shadow: 0 10px 24px rgba(0, 0, 0, 0.08);
  text-align: center;
}
.register-box h1 {
  font-size: 22px;
  margin-bottom: 24px;
}
.login-link {
  margin-top: 18px;
  font-size: 14px;
  color: #666;
}
.login-link a {
  color: var(--el-color-primary);
}
</style>
