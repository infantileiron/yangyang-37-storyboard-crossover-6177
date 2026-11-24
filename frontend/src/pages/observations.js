import { download, get, importFile, post } from '../api/client.js';
import { table } from '../components/common/data.js';
import { intro } from '../components/common/frame.js';
import { fieldControl, formError } from '../components/common/forms.js';
import { Role } from '../constants/enums.js';
import { bindDownloads, bindForm, notify } from '../hooks/actions.js';
import { formValues } from '../types/form.js';
import { esc, timeLabel } from '../utils/html.js';

function correctionSection(sheets, effective, writable) {
  const excluded = effective.excluded;
  const summary = `已生效更正单 ${effective.sheet_count} 张 · 按修订覆盖 ${effective.rows.filter(row => row.origin === 'correction').length} 名审修员 · 剔除 ${excluded.length} 名`;
  const importer = writable ? `<details><summary>导入计时更正单</summary><form id="correction-form"><p>整单在一个事务内生效；按审修员与修订号合并，重试导入不重复计入。迟到低版不会顶掉更高版。</p><button type="button" data-download="/corrections/template">下载更正单模板</button><label class="field"><span>CSV 文件</span><input type="file" name="file" accept=".csv,text/csv" required></label>${formError}<button class="primary">导入更正单</button></form></details>` : '';
  const excludedTable = excluded.length
    ? table([{key:'reviewer',label:'被剔除审修员'},{key:'revision',label:'冲突修订号'},{key:'reason',label:'处理方式'}], excluded, '')
    : '<p class="aside-note">当前没有被剔除的审修员。</p>';
  return `<section class="panel"><div class="panel-heading"><h2>计时更正单</h2><span class="aside-note">${esc(summary)}</span></div><div class="panel-body">${importer}
    ${table([{key:'id',label:'单号'},{key:'record_count',label:'记录数'},{key:'imported_by',label:'导入人'},{label:'导入时间',html:row => timeLabel(row.created_at)}], sheets, '还没有收到更正单。')}
    ${excludedTable}</div></section>`;
}

export async function observationPage(spec, user, route) {
  const offset = Math.max(0, Number.parseInt(route.id, 10) || 0);
  const writable = user.role !== Role.VIEWER;
  const [{total, items}, sheets, effective] = await Promise.all([
    get(`/observations?offset=${offset}&limit=20`), get('/corrections'), get('/corrections/effective')]);
  return `${intro('数据台账', spec.source, `<span class="count">${total} <small>条${esc(spec.record_name)}</small></span>`)}
    ${writable ? `<div class="tools"><details><summary>登记一条${esc(spec.record_name)}</summary><form id="record-form"><div class="form-grid">${spec.fields.map(field => fieldControl(field)).join('')}</div>${formError}<button class="primary">保存记录</button></form></details>
    <details><summary>按模板导入 CSV</summary><form id="import-form"><p>使用 UTF-8 CSV，每次最多 500 条。重复行自动跳过。</p><button type="button" data-download="/observations/template">下载模板</button><label class="field"><span>CSV 文件</span><input type="file" name="file" accept=".csv,text/csv" required></label>${formError}<button class="primary">导入文件</button></form></details></div>` : ''}
    <section class="panel"><div class="panel-heading"><h2>${esc(spec.record_name)}明细</h2>${writable ? '<a class="text-link" href="#analysis">发起分析 →</a>' : ''}</div>
    ${table([{key:'id',label:'记录号'},...spec.fields], items.map(item => ({id:item.id,...item.data})), '暂无观测。分析员可先导入 CSV 或登记样本。')}
    ${total ? `<div class="pagination"><span>第 ${offset + 1}–${Math.min(total,offset + 20)} 条</span>${offset > 0 ? `<a href="#observations/${Math.max(0, offset-20)}">上一页</a>` : ''}${offset+20 < total ? `<a href="#observations/${offset+20}">下一页</a>` : ''}</div>` : ''}</section>
    ${correctionSection(sheets, effective, writable)}`;
}

export function wireObservations(root, spec, refresh) {
  bindDownloads(root, download);
  bindForm(root.querySelector('#record-form'), async form => {
    await post('/observations', formValues(form, spec.fields));
    notify('记录已保存');
    if (location.hash === '#observations' || !location.hash) refresh();
    else location.hash = '#observations';
  });
  bindForm(root.querySelector('#import-form'), async form => {
    const report = await importFile(form.elements.file.files[0]);
    notify(`已导入 ${report.added} 条 · 跳过 ${report.skipped} 条重复记录`);
    refresh();
  });
  bindForm(root.querySelector('#correction-form'), async form => {
    const report = await importFile(form.elements.file.files[0], '/corrections/import');
    notify(report.already_imported ? `更正单 #${report.sheet_id} 已导入过，未重复计入`
           : `更正单 #${report.sheet_id} 已生效 · 新计入 ${report.added} 条 · 跳过 ${report.skipped} 条`);
    refresh();
  });
}
