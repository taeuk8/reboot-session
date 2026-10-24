document.querySelector('#save').addEventListener('click', async () => {
  const status = document.querySelector('#status');
  try {
    const profile = document.querySelector('#profile').value.trim();
    if (!profile || /[\\/]/.test(profile) || profile.startsWith('-')) throw new Error('프로필 폴더 이름을 확인하세요.');
    const windows = (await chrome.windows.getAll({populate: true, windowTypes: ['normal']}))
      .filter(w => !w.incognito)
      .map(w => ({tabs: w.tabs.map(t => ({url: t.url || t.pendingUrl || '', active: t.active, pinned: t.pinned}))}));
    const value = {format: 'reboot-session-chrome-v1', captured_at: new Date().toISOString(), profile, windows};
    const blob = new Blob([JSON.stringify(value, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    await chrome.downloads.download({url, filename: `reboot-chrome-${Date.now()}.json`, saveAs: true});
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    status.textContent = `${windows.length}개 창을 내보냈습니다. 앱에서 JSON을 가져오세요.`;
  } catch (error) { status.textContent = error.message; }
});
