/**
 * dashboard_charts.js
 * Reads colors from CSS variables so charts stay correct in both themes.
 * Charts are built ONCE per page load. On themeChanged we patch colors
 * in-place and call .update() — no destroy+recreate, which was causing
 * the infinite resize loop together with the missing fixed-height wrapper.
 */

/* ── helpers ── */
function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function isDark() {
    return document.documentElement.getAttribute('data-theme') === 'dark';
}

function chartTextColor()  { return cssVar('--text-main')  || (isDark() ? '#e2e8f0' : '#334155'); }
function chartMutedColor() { return cssVar('--text-muted') || (isDark() ? '#94a3b8' : '#64748b'); }
function chartGridColor()  { return isDark() ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.05)'; }
function tooltipBg()       { return isDark() ? '#1e293b' : 'rgba(255,255,255,0.97)'; }
function tooltipText()     { return isDark() ? '#e2e8f0' : '#1e293b'; }
function tooltipBorder()   { return isDark() ? '#334155' : '#e2e8f0'; }

/* ── shared defaults applied to every chart ── */
function applyGlobalDefaults() {
    Chart.defaults.color  = chartTextColor();
    Chart.defaults.borderColor = chartGridColor();
}

/* ════════════════════════════════════════════════
   LEADS  — Doughnut
════════════════════════════════════════════════ */
let leadsChartInstance = null;

function buildLeadsChart(leadsData) {
    const canvas = document.getElementById('leadsChart');
    if (!canvas || !leadsData || leadsData.length === 0) return;

    // Destroy any existing instance (Chart.getChart is the safe guard)
    const existing = Chart.getChart(canvas);
    if (existing) existing.destroy();
    leadsChartInstance = null;

    const totalLeads = leadsData.reduce((s, i) => s + i.count, 0);
    const labels     = leadsData.map(i => `${i.status_label} \u00b7 ${i.count}`);
    const data       = leadsData.map(i => i.count);

    const colorMap = {
        'New':         '#3b82f6',
        'Contacted':   '#8b5cf6',
        'In Progress': '#f59e0b',
        'Converted':   '#10b981',
        'Lost':        '#ef4444'
    };
    const bgColors = leadsData.map(i => colorMap[i.status_label] || '#94a3b8');

    /* Center-text plugin reads live CSS vars on every draw so theme
       changes are reflected without destroying the chart. */
    const centerTextPlugin = {
        id: 'centerText',
        beforeDraw(chart) {
            if (chart.config.type !== 'doughnut') return;
            const { width, height, ctx } = chart;
            ctx.restore();

            const fs = Math.max(1, (height / 120)).toFixed(2);
            ctx.font         = `bold ${fs}em Inter,sans-serif`;
            ctx.fillStyle    = chartTextColor();
            ctx.textBaseline = 'middle';
            const text  = totalLeads.toString();
            const textX = Math.round((width - ctx.measureText(text).width) / 2);
            const textY = height / 2.2;
            ctx.fillText(text, textX, textY);

            ctx.font      = `normal ${(fs * 0.4).toFixed(2)}em Inter,sans-serif`;
            ctx.fillStyle = chartMutedColor();
            const sub  = 'Total';
            const subX = Math.round((width - ctx.measureText(sub).width) / 2);
            ctx.fillText(sub, subX, textY + 22);

            ctx.save();
        }
    };

    leadsChartInstance = new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels,
            datasets: [{ data, backgroundColor: bgColors, borderWidth: 0, hoverOffset: 4 }]
        },
        options: {
            responsive:          true,
            maintainAspectRatio: false,
            cutout: '70%',
            layout: { padding: { bottom: 16 } },
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { usePointStyle: true, boxWidth: 8, padding: 14, color: chartTextColor() }
                }
            }
        },
        plugins: [centerTextPlugin]
    });
}

/* Patch leads chart colors in-place — no destroy */
function updateLeadsChartColors() {
    if (!leadsChartInstance) return;
    leadsChartInstance.options.plugins.legend.labels.color = chartTextColor();
    leadsChartInstance.update();
}

/* ════════════════════════════════════════════════
   ORDERS  — Line / Bar (bar when ≤ 2 points)
════════════════════════════════════════════════ */
let ordersChartInstance = null;

function buildOrdersChart(ordersData) {
    const canvas = document.getElementById('ordersChart');
    if (!canvas || !ordersData || ordersData.length === 0) return;

    // Destroy any existing instance safely
    const existing = Chart.getChart(canvas);
    if (existing) existing.destroy();
    ordersChartInstance = null;

    const labels    = ordersData.map(i => i.month);
    const data      = ordersData.map(i => i.count);
    const ctx       = canvas.getContext('2d');
    const fewPoints = data.length <= 2;
    const chartType = fewPoints ? 'bar' : 'line';

    // Show/hide the sparse-data hint
    const notEnoughNote = document.getElementById('ordersChartNote');
    if (notEnoughNote) notEnoughNote.style.display = fewPoints ? 'block' : 'none';

    let gradient = null;
    if (!fewPoints) {
        gradient = ctx.createLinearGradient(0, 0, 0, 280);
        gradient.addColorStop(0, 'rgba(16,185,129,0.35)');
        gradient.addColorStop(1, 'rgba(16,185,129,0.00)');
    }

    const datasetConfig = fewPoints
        ? {
            backgroundColor: 'rgba(16,185,129,0.65)',
            borderRadius:    6,
            maxBarThickness: 48,
            barPercentage:   0.5,
            categoryPercentage: 0.6
          }
        : {
            borderColor:          '#10b981',
            backgroundColor:      gradient,
            borderWidth:          2,
            pointBackgroundColor: isDark() ? '#1e293b' : '#fff',
            pointBorderColor:     '#10b981',
            pointBorderWidth:     2,
            pointRadius:          4,
            pointHoverRadius:     6,
            fill:    true,
            tension: 0.4
          };

    ordersChartInstance = new Chart(ctx, {
        type: chartType,
        data: {
            labels,
            datasets: [{ label: 'Orders', data, ...datasetConfig }]
        },
        options: {
            responsive:          true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: tooltipBg(),
                    titleColor:      tooltipText(),
                    bodyColor:       tooltipText(),
                    borderColor:     tooltipBorder(),
                    borderWidth:     1,
                    padding:         10,
                    displayColors:   false
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: { stepSize: 1, precision: 0, color: chartMutedColor() },
                    grid:  { color: chartGridColor(), drawBorder: false }
                },
                x: {
                    ticks: { color: chartMutedColor() },
                    grid:  { display: false }
                }
            }
        }
    });
}

/* Patch orders chart colors in-place — no destroy */
function updateOrdersChartColors() {
    if (!ordersChartInstance) return;
    const opts = ordersChartInstance.options;
    opts.scales.y.ticks.color = chartMutedColor();
    opts.scales.x.ticks.color = chartMutedColor();
    opts.scales.y.grid.color  = chartGridColor();
    const tip = opts.plugins.tooltip;
    tip.backgroundColor = tooltipBg();
    tip.titleColor      = tooltipText();
    tip.bodyColor       = tooltipText();
    tip.borderColor     = tooltipBorder();
    const ds = ordersChartInstance.data.datasets[0];
    if (ds && ordersChartInstance.config.type === 'line') {
        ds.pointBackgroundColor = isDark() ? '#1e293b' : '#fff';
    }
    ordersChartInstance.update();
}

/* ════════════════════════════════════════════════
   INIT  +  THEME CHANGE LISTENER (registered once)
════════════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', function () {
    applyGlobalDefaults();

    const leadsEl  = document.getElementById('leadsChartData');
    const ordersEl = document.getElementById('ordersChartData');
    const leadsData  = leadsEl  ? JSON.parse(leadsEl.textContent)  : null;
    const ordersData = ordersEl ? JSON.parse(ordersEl.textContent) : null;

    buildLeadsChart(leadsData);
    buildOrdersChart(ordersData);

    /* On theme change: update colors in-place.
       rAF ensures CSS vars have been re-evaluated before we read them. */
    window.addEventListener('themeChanged', function () {
        applyGlobalDefaults();
        requestAnimationFrame(function () {
            updateLeadsChartColors();
            updateOrdersChartColors();
        });
    });
});
