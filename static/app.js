const fileInput = document.getElementById('fileInput');
const uploadBtn = document.getElementById('uploadBtn');
const generateBtn = document.getElementById('generateBtn');
const historyBody = document.getElementById('historyBody');
const historyRowTemplate = document.getElementById('historyRowTemplate');
const historyCount = document.getElementById('historyCount');
const templateList = document.getElementById('templateList');
const templateItemTemplate = document.getElementById('templateItemTemplate');
const templateCount = document.getElementById('templateCount');
const toast = document.getElementById('toast');

let historyRecords = [];
let templateRecords = [];
let selectedHistoryId = null;

async function init() {
  await Promise.all([refreshHistory(), refreshTemplates()]);
  bindEvents();
}

function bindEvents() {
  uploadBtn.addEventListener('click', handleUpload);
  generateBtn.addEventListener('click', handleGenerate);
}

async function handleUpload() {
  if (!fileInput.files || fileInput.files.length === 0) {
    showToast('请先选择一个文件');
    return;
  }

  const formData = new FormData();
  formData.append('file', fileInput.files[0]);

  toggleUploadButtons(true);
  try {
    const response = await fetch('/api/upload', {
      method: 'POST',
      body: formData,
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.error || '上传失败');
    }
    showToast('上传成功');
    fileInput.value = '';
    await refreshHistory();
    selectedHistoryId = result.id;
    highlightSelected();
  } catch (error) {
    console.error(error);
    showToast(error.message);
  } finally {
    toggleUploadButtons(false);
  }
}

async function handleGenerate() {
  const targetId = selectedHistoryId || historyRecords.find((item) => item.status !== 'converted')?.id;
  if (!targetId) {
    showToast('请先选择需要生成PDF的文件');
    return;
  }
  await convertHistory(targetId);
}

async function convertHistory(historyId) {
  try {
    const response = await fetch('/api/convert', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ history_id: historyId }),
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.error || '转换失败');
    }
    showToast('PDF生成成功');
    await refreshHistory();
    selectedHistoryId = historyId;
    highlightSelected();
  } catch (error) {
    console.error(error);
    showToast(error.message);
  }
}

async function refreshHistory() {
  const response = await fetch('/api/history');
  historyRecords = await response.json();
  renderHistory();
}

function renderHistory() {
  historyBody.innerHTML = '';
  historyCount.textContent = historyRecords.length;

  historyRecords.forEach((record) => {
    const fragment = historyRowTemplate.content.cloneNode(true);
    const row = fragment.querySelector('tr');
    const radio = fragment.querySelector('input[type="radio"]');
    const filenameCell = fragment.querySelector('.filename');
    const statusCell = fragment.querySelector('.status');
    const uploadedCell = fragment.querySelector('.uploaded-at');
    const actionsCell = fragment.querySelector('.actions');

    filenameCell.textContent = record.filename;
    statusCell.textContent = record.status === 'converted' ? '已生成PDF' : '待生成';
    statusCell.classList.add('status', record.status);
    uploadedCell.textContent = formatDate(record.uploaded_at);

    radio.checked = record.id === selectedHistoryId;
    radio.addEventListener('change', () => {
      selectedHistoryId = record.id;
      highlightSelected();
    });

    const convertBtn = document.createElement('button');
    convertBtn.textContent = record.status === 'converted' ? '重新生成' : '生成PDF';
    convertBtn.addEventListener('click', () => convertHistory(record.id));

    const deleteBtn = document.createElement('button');
    deleteBtn.textContent = '删除';
    deleteBtn.classList.add('danger');
    deleteBtn.addEventListener('click', () => deleteHistory(record.id));

    const templateBtn = document.createElement('button');
    templateBtn.textContent = '保存为模板';
    templateBtn.addEventListener('click', () => createTemplate(record.id));

    actionsCell.appendChild(convertBtn);
    if (record.download_url) {
      const downloadLink = document.createElement('a');
      downloadLink.href = record.download_url;
      downloadLink.textContent = '下载PDF';
      downloadLink.target = '_blank';
      actionsCell.appendChild(downloadLink);
    }
    actionsCell.appendChild(templateBtn);
    actionsCell.appendChild(deleteBtn);

    historyBody.appendChild(fragment);
    if (radio.checked) {
      row.classList.add('selected');
    }
  });

  if (!selectedHistoryId && historyRecords.length > 0) {
    selectedHistoryId = historyRecords[0].id;
    highlightSelected();
  }
}

async function deleteHistory(historyId) {
  if (!confirm('确认删除该条历史记录？')) {
    return;
  }
  const response = await fetch(`/api/history/${historyId}`, {
    method: 'DELETE',
  });
  const result = await response.json();
  if (!response.ok) {
    showToast(result.error || '删除失败');
    return;
  }
  showToast('已删除');
  await Promise.all([refreshHistory(), refreshTemplates()]);
  if (selectedHistoryId === historyId) {
    selectedHistoryId = null;
  }
}

async function createTemplate(historyId) {
  const name = prompt('为模板输入一个名称：');
  if (name === null) {
    return;
  }
  const response = await fetch('/api/templates', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ history_id: historyId, name: name.trim() || undefined }),
  });
  const result = await response.json();
  if (!response.ok) {
    showToast(result.error || '创建模板失败');
    return;
  }
  showToast('模板已保存');
  await refreshTemplates();
}

async function refreshTemplates() {
  const response = await fetch('/api/templates');
  templateRecords = await response.json();
  renderTemplates();
}

function renderTemplates() {
  templateList.innerHTML = '';
  templateCount.textContent = templateRecords.length;

  templateRecords.forEach((template) => {
    const fragment = templateItemTemplate.content.cloneNode(true);
    const item = fragment.querySelector('.template-item');
    fragment.querySelector('.template-name').textContent = template.name;
    fragment.querySelector('.template-date').textContent = `创建于 ${formatDate(template.created_at)}`;

    const actions = fragment.querySelector('.template-actions');
    const useBtn = document.createElement('button');
    useBtn.textContent = '应用模板';
    useBtn.addEventListener('click', () => useTemplate(template.id));

    const deleteBtn = document.createElement('button');
    deleteBtn.textContent = '删除';
    deleteBtn.classList.add('danger');
    deleteBtn.addEventListener('click', () => deleteTemplate(template.id));

    actions.appendChild(useBtn);
    if (template.download_url) {
      const downloadLink = document.createElement('a');
      downloadLink.href = template.download_url;
      downloadLink.textContent = '下载模板';
      downloadLink.target = '_blank';
      actions.appendChild(downloadLink);
    }
    actions.appendChild(deleteBtn);

    templateList.appendChild(fragment);
  });
}

async function deleteTemplate(templateId) {
  if (!confirm('确认删除该模板？')) {
    return;
  }
  const response = await fetch(`/api/templates/${templateId}`, {
    method: 'DELETE',
  });
  const result = await response.json();
  if (!response.ok) {
    showToast(result.error || '删除模板失败');
    return;
  }
  showToast('模板已删除');
  await refreshTemplates();
}

async function useTemplate(templateId) {
  const name = prompt('使用模板创建新文件，可修改文件名：');
  const response = await fetch(`/api/templates/${templateId}/use`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ name: name && name.trim() ? name.trim() : undefined }),
  });
  const result = await response.json();
  if (!response.ok) {
    showToast(result.error || '应用模板失败');
    return;
  }
  showToast('模板已应用，生成新的历史记录');
  await refreshHistory();
  selectedHistoryId = result.id;
  highlightSelected();
}

function highlightSelected() {
  Array.from(document.querySelectorAll('#historyBody tr')).forEach((row) => {
    row.classList.remove('selected');
  });
  const selectedRadio = Array.from(document.querySelectorAll('.history-select')).find(
    (radio) => radio.checked
  );
  if (selectedRadio) {
    selectedRadio.closest('tr').classList.add('selected');
  }
}

function toggleUploadButtons(disabled) {
  uploadBtn.disabled = disabled;
  generateBtn.disabled = disabled;
}

function formatDate(value) {
  if (!value) return '-';
  try {
    return new Date(value).toLocaleString();
  } catch (error) {
    return value;
  }
}

let toastTimer = null;
function showToast(message) {
  toast.textContent = message;
  toast.classList.remove('hidden');
  toast.classList.add('show');
  if (toastTimer) {
    clearTimeout(toastTimer);
  }
  toastTimer = setTimeout(() => {
    toast.classList.remove('show');
    toastTimer = setTimeout(() => {
      toast.classList.add('hidden');
    }, 300);
  }, 2600);
}

init();
