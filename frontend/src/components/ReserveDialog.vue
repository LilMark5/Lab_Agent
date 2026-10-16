<template>
  <el-dialog
    :model-value="visible"
    title="预约"
    width="460px"
    @open="resetFields"
    @close="emit('update:visible', false)"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
      <el-form-item label="实验室">
        <el-input :model-value="labName" disabled />
      </el-form-item>
      <el-form-item v-if="equipmentName" label="设备">
        <el-input :model-value="equipmentName" disabled />
      </el-form-item>
      <el-form-item label="预约日期" prop="date">
        <el-date-picker
          v-model="form.date"
          type="date"
          value-format="YYYY-MM-DD"
          format="YYYY-MM-DD"
          placeholder="请选择日期"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="开始时间" prop="startTime">
        <el-time-picker
          v-model="form.startTime"
          value-format="HH:mm"
          format="HH:mm"
          placeholder="开始时间"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="结束时间" prop="endTime">
        <el-time-picker
          v-model="form.endTime"
          value-format="HH:mm"
          format="HH:mm"
          placeholder="结束时间"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="form.remark" type="textarea" :rows="2" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:visible', false)">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="handleSubmit">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { createReservationApi } from '@/api/reservation'

const props = defineProps({
  visible: Boolean,
  labId: Number,
  labName: String,
  equipmentId: Number,
  equipmentName: String
})
const emit = defineEmits(['update:visible'])

const formRef = ref()
const submitting = ref(false)
const form = reactive({ date: '', startTime: '09:00', endTime: '11:00', remark: '' })

const rules = {
  date: [{ required: true, message: '请选择预约日期', trigger: 'change' }],
  startTime: [{ required: true, message: '请选择开始时间', trigger: 'change' }],
  endTime: [{ required: true, message: '请选择结束时间', trigger: 'change' }]
}

const resetFields = () => {
  Object.assign(form, { date: '', startTime: '09:00', endTime: '11:00', remark: '' })
  formRef.value?.clearValidate()
}

const handleSubmit = async () => {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    const res = await createReservationApi({
      lab_id: props.labId,
      equipment_id: props.equipmentId,
      date: form.date,
      start_time: form.startTime,
      end_time: form.endTime,
      remark: form.remark
    })
    if (res.code === 200) {
      ElMessage.success('预约已提交，请等待审核')
      emit('update:visible', false)
    }
  } finally {
    submitting.value = false
  }
}
</script>
