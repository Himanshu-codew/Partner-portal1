/**
 * dashboard_charts.js
 * Reads colors from CSS variables so charts stay correct in both themes.
 * Re-renders on 'themeChanged' event dispatched by the topbar toggle.
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

    const totalLeads = leadsData.reduce((s, i) => s + i.count, 0);
    const labels = leadsData.map(i => `${i.status_label} · ${i.count}`);
    const data   = leadsData.map(i => i.count);

    const colorMap = {
        'New':         '#3b82f6',
        'Contacted':   '#8b5cf6',
        'In Progress': '#f59e0b',
        'Converted':   '#10b981',
        'Lost':        '#ef4444'
    };
    const bgColors = leadsData.map(i => colorMap[i.status_label] || '#94a3b8');

    const centerTextPlugin = {
        id: 'centerText',
        beforeDraw(chart) {
            if (chart.config.type !== 'doughnut') return;
            const { width, height, ctx } = chart;
            ctx.restore();

            // Main number
            const fs = (height / 120).toFixed(2);
            ctx.font       = `bold ${fs}em Inter,sans-serif`;
            ctx.fillStyle  = chartTextColor();
            ctx.textBaseline = 'middle';
            const text  = totalLeads.toString();
            const textX = Math.round((width - ctx.measureText(text).width) / 2);
            const textY = height / 2.2;
            ctx.fillText(text, textX, textY);

            // Sub-label
            ctx.font      = `normal ${(fs * 0.4).toFixed(2)}em Inter,sans-serif`;
            ctx.fillStyle = chartMutedColor();
            const sub  = 'Total';
            const subX = Math.round((width - ctx.measureText(sub).width) / 2);
            ctx.fillText(sub, subX, textY + 22);

            ctx.save();
        }
    };

    if (leadsChartInstance) { leadsChartInstance.destroy(); }

    leadsChartInstance = new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels,
            datasets: [{ data, backgroundColor: bgColors, borderWidth: 0, hoverOffset: 4 }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            layout: { padding: { bottom: 20 } },
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { usePointStyle: true, boxWidth: 8, padding: 15, color: chartTextColor() }
                }
            },
            cutout: '75%'
        },
        plugins: [centerTextPlugin]
    });
}

/* ════════════════════════════════════════════════
   ORDERS  — Line / Bar (bar when ≤ 2 points)
════════════════════════════════════════════════ */
let ordersChartInstance = null;

function buildOrdersChart(ordersData) {
    const canvas = document.getElementById('ordersChart');
    if (!canvas || !ordersData || ordersData.length === 0) return;

    const labels = ordersData.map(i => i.month);
    const data   = ordersData.map(i => i.count);
    const ctx    = canvas.getContext('2d');

    // Use bar chart for sparse data; prevents the "single-dot" problem
    const fewPoints = data.length <= 2;
    const chartType = fewPoints ? 'bar' : 'line';

    // Add a note for very sparse data
    const notEnoughNote = document.getElementById('ordersChartNote');
    if (fewPoints && notEnoughNote) {
        notEnoughNote.style.display = 'block';
    }

    let gradient = null;
    if (!fewPoints) {
        gradient = ctx.createLinearGradient(0, 0, 0, 300);
        gradient.addColorStop(0, 'rgba(16,185,129,0.35)');
        gradient.addColorStop(1, 'rgba(16,185,129,0.0)');
    }

    const datasetConfig = fewPoints
        ? { backgroundColor: 'rgba(16,185,129,0.6)', borderRadius: 6 }
        : {
            borderColor: '#10b981',
            backgroundColor: gradient,
            borderWidth: 2,
            pointBackgroundColor: isDark() ? '#1e293b' : '#fff',
            pointBorderColor: '#10b981',
            pointBorderWidth: 2,
            pointRadius: 4,
            pointHoverRadius: 6,
            fill: true,
            tension: 0.4
          };

    if (ordersChartInstance) { ordersChartInstance.destroy(); }

    ordersChartInstance = new Chart(ctx, {
        type: chartType,
        data: {
            labels,
            datasets: [{ label: 'Orders', data, ...datasetConfig }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: tooltipBg(),
                    titleColor: tooltipText(),
                    bodyColor: tooltipText(),
                    borderColor: tooltipBorder(),
                    borderWidth: 1,
                    padding: 10,
                    displayColors: false
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        stepSize: 1,
                        precision: 0,
                        color: chartMutedColor()
                    },
                    grid: { color: chartGridColor(), drawBorder: false }
                },
                x: {
                    ticks: { color: chartMutedColor() },
                    grid: { display: false }
                }
            }
        }
    });
}

/* ════════════════════════════════════════════════
   INIT  +  THEME CHANGE LISTENER
════════════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', function () {
    applyGlobalDefaults();

    const leadsEl  = document.getElementById('leadsChartData');
    const ordersEl = document.getElementById('ordersChartData');

    const leadsData  = leadsEl  ? JSON.parse(leadsEl.textContent)  : null;
    const ordersData = ordersEl ? JSON.parse(ordersEl.textContent) : null;

    buildLeadsChart(leadsData);
    buildOrdersChart(ordersData);

    // Re-render charts when theme changes
    window.addEventListener('themeChanged', function () {
        applyGlobalDefaults();
        // Small delay so CSS vars are updated first
        requestAnimationFrame(() => {
            buildLeadsChart(leadsData);
            buildOrdersChart(ordersData);
        });
    });
});
