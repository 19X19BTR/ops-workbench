'use strict';
/**
 * 分类逻辑测试：把页面里的脚本放进 vm 跑，不需要浏览器、不打开文件。
 *
 *   node tests/classify.test.cjs
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const ROOT = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(ROOT, 'workbench', 'index.html'), 'utf8');
const config = JSON.parse(fs.readFileSync(path.join(ROOT, 'config', 'config.example.json'), 'utf8'));

// 只取 <script> 内容，并在绑定 DOM 的那一段之前截断（那之后的代码需要浏览器环境）
let script = html.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
const cutAt = script.indexOf("const settings=");
if (cutAt < 0) throw new Error('找不到截断点，页面结构可能变了');
script = script.slice(0, cutAt);

const context = vm.createContext({
  console, JSON, RegExp, Map, Set, Object, Array, String, Number, Math, Intl, Date,
});
vm.runInContext(script, context);
vm.runInContext(`catalogKnowledge = buildKnowledge(${JSON.stringify(config.classify)});`, context);

const HEADERS = ['优先商品名称', '聚水潭商品名称', '类型候选', '材质候选', '颜色候选',
                 '规格原文', '源颜色字段', '商品编码'];

function classify({ name = '', alias = '', type = '', material = '', color = '',
                    spec = '', sourceColor = '', code = '' } = {}) {
  context.fixture = { safeHeaders: HEADERS, rows: [] };
  context.row = [name, alias, type, material, color, spec, sourceColor, code];
  return vm.runInContext('classifyCatalog(fixture, row)', context);
}

const tests = [];
const test = (name, fn) => tests.push({ name, fn });
const eq = (actual, expected, label) => assert.strictEqual(actual, expected, `${label}: 期望 ${expected}，实际 ${actual}`);

// ---------- 类型 ----------
test('类型：源表值优先于名称', () => eq(classify({ name: '水晶手链', type: '戒指' })['类型候选'], '戒指', '类型'));
test('类型：待核回退到名称', () => eq(classify({ name: '紫水晶手链', type: '待核' })['类型候选'], '手串', '类型'));
test('类型：项链识别', () => eq(classify({ name: '珍珠项链' })['类型候选'], '项链', '类型'));
test('类型：耳饰识别', () => eq(classify({ name: '银耳钉' })['类型候选'], '耳饰', '类型'));
test('类型：珠料识别', () => eq(classify({ name: '碧玺圆珠' })['类型候选'], '珠料', '类型'));
test('类型：无任何线索 → 不适用（原料名称线索）',
     () => eq(classify({ name: '未知商品 X-001' })['类型候选'], '不适用（原料名称线索）', '类型'));
test('类型：命中品牌标记 → 成品类型未分类',
     () => eq(classify({ name: '示例原料 木珠散装' })['类型候选'], '成品类型未分类', '类型'));

// ---------- 材质 ----------
test('材质：名称识别水晶', () => eq(classify({ name: '紫水晶手串' })['材质候选'], '水晶', '材质'));
test('材质：925 银识别', () => eq(classify({ name: 'S925银戒指' })['材质候选'], '银', '材质'));
test('材质：源表值优先', () => eq(classify({ name: '未知', material: '翡翠' })['材质候选'], '翡翠', '材质'));
test('材质：金属与主石并存时优先主石',
     () => eq(classify({ name: 'S925银水晶手链' })['材质候选'], '水晶', '材质'));
test('材质：无线索兜底', () => eq(classify({ name: '未知商品 X-001' })['材质候选'], '材质未分类', '材质'));

// ---------- 颜色 ----------
test('颜色：源表值优先', () => eq(classify({ name: '蓝水晶', color: '红' })['颜色候选'], '红', '颜色'));
test('颜色：按材料后缀识别', () => eq(classify({ name: '蓝托帕项链' })['颜色候选'], '蓝', '颜色'));
test('颜色：明示色词不加推定标记', () => eq(classify({ name: '粉水晶单圈 9mm' })['颜色候选'], '粉', '颜色'));
test('颜色：别名推定（藕粉）', () => eq(classify({ name: '藕粉 单圈 10mm' })['颜色候选'],
                                        '粉（按名称推定）', '颜色'));
test('颜色：名称推定需源颜色条件（茶晶单圈）',
     () => eq(classify({ name: '茶晶单圈 10mm', sourceColor: '茶色' })['颜色候选'],
             '茶棕灰（按茶色名称推定）', '颜色'));
test('颜色：材料颜色规则（茶晶非单圈）',
     () => eq(classify({ name: '茶晶圆珠 8mm' })['颜色候选'], '茶棕灰（按茶晶名称推定）', '颜色'));
test('颜色：孔雀石按材料推定',
     () => eq(classify({ name: '孔雀石摆件' })['颜色候选'], '绿（按孔雀石名称推定）', '颜色'));
test('颜色：仿制品不做颜色推定',
     () => eq(classify({ name: '仿水晶手串' })['颜色候选'], '颜色未分类', '颜色'));

// ---------- 多品/多色 ----------
test('多宝：命中明确编码', () => eq(classify({ name: '多宝手串', code: 'MB20260001' })['颜色候选'],
                                     '多宝', '颜色'));
test('多色系：单色材料未给颜色',
     () => eq(classify({ name: '碧玺圆珠 4mm' })['颜色候选'], '多色系', '颜色'));

// ---------- 组合 ----------
test('组合：一条完整行', () => {
  const result = classify({ name: '紫水晶手串 8mm', type: '待核', color: '待核' });
  eq(result['类型候选'], '手串', '类型');
  eq(result['材质候选'], '水晶', '材质');
  eq(result['颜色候选'], '紫', '颜色');
});

// ---------- 配置可替换性 ----------
test('配置驱动：换一套词库立即生效', () => {
  const custom = JSON.parse(JSON.stringify(config.classify));
  custom.type = [['测试类型', '测试词']];
  custom.material = [['测试材质', '测试词']];
  vm.runInContext(`catalogKnowledge = buildKnowledge(${JSON.stringify(custom)});`, context);
  const result = classify({ name: '测试词商品' });
  eq(result['类型候选'], '测试类型', '类型');
  eq(result['材质候选'], '测试材质', '材质');
  // 还原，避免影响后续用例
  vm.runInContext(`catalogKnowledge = buildKnowledge(${JSON.stringify(config.classify)});`, context);
});

// ---------- 执行 ----------
let passed = 0;
const failures = [];
for (const { name, fn } of tests) {
  try { fn(); passed += 1; } catch (err) { failures.push(`${name}\n    ${err.message}`); }
}
console.log(`分类测试：${passed}/${tests.length} 通过`);
if (failures.length) {
  console.error('\n失败用例：');
  failures.forEach(f => console.error('  ✗ ' + f));
  process.exit(1);
}
