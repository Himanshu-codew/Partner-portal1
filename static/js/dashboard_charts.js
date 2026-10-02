document.addEventListener("DOMContentLoaded", function() {
    // 1. Leads Doughnut Chart
    const leadsDataElement = document.getElementById('leadsChartData');
    if (leadsDataElement) {
        const leadsData = JSON.parse(leadsDataElement.textContent);
        if (leadsData.length > 0) {
            const totalLeads = leadsData.reduce((sum, item) => sum + item.count, 0);
            
            // Append count to legend labels
            const labels = leadsData.map(item => `${item.status_label} · ${item.count}`);
            const data = leadsData.map(item => item.count);
            
            const colorMap = {
                'New': '#3b82f6', // primary
                'Contacted': '#8b5cf6', // purple
                'In Progress': '#f59e0b', // warning
                'Converted': '#10b981', // success
                'Lost': '#ef4444' // danger
            };
            const bgColors = leadsData.map(item => colorMap[item.status_label] || '#94a3b8');

            // Custom plugin for total in center
            const centerTextPlugin = {
                id: 'centerText',
                beforeDraw: function(chart) {
                    if (chart.config.type !== 'doughnut') return;
                    var width = chart.width,
                        height = chart.height,
                        ctx = chart.ctx;
            
                    ctx.restore();
                    var fontSize = (height / 120).toFixed(2);
                    ctx.font = "bold " + fontSize + "em sans-serif";
                    ctx.textBaseline = "middle";
                    ctx.fillStyle = "#334155";
            
                    var text = totalLeads.toString(),
                        textX = Math.round((width - ctx.measureText(text).width) / 2),
                        textY = height / 2.2;
            
                    ctx.fillText(text, textX, textY);
                    
                    ctx.font = "normal " + (fontSize * 0.4).toFixed(2) + "em sans-serif";
                    ctx.fillStyle = "#64748b";
                    var subText = "Total",
                        subTextX = Math.round((width - ctx.measureText(subText).width) / 2),
                        subTextY = height / 2.2 + 25;
                    ctx.fillText(subText, subTextX, subTextY);
                    
                    ctx.save();
                }
            };

            new Chart(document.getElementById('leadsChart'), {
                type: 'doughnut',
                data: {
                    labels: labels,
                    datasets: [{
                        data: data,
                        backgroundColor: bgColors,
                        borderWidth: 0,
                        hoverOffset: 4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    layout: {
                        padding: { bottom: 20 }
                    },
                    plugins: {
                        legend: {
                            position: 'bottom',
                            labels: { 
                                usePointStyle: true, 
                                boxWidth: 8,
                                padding: 15
                            }
                        }
                    },
                    cutout: '75%'
                },
                plugins: [centerTextPlugin]
            });
        }
    }

    // 2. Orders Area Chart
    const ordersDataElement = document.getElementById('ordersChartData');
    if (ordersDataElement) {
        const ordersData = JSON.parse(ordersDataElement.textContent);
        if (ordersData.length > 0) {
            const labels = ordersData.map(item => item.month);
            const data = ordersData.map(item => item.count);

            const ctx = document.getElementById('ordersChart').getContext('2d');
            const gradient = ctx.createLinearGradient(0, 0, 0, 400);
            gradient.addColorStop(0, 'rgba(16, 185, 129, 0.4)');
            gradient.addColorStop(1, 'rgba(16, 185, 129, 0.0)');

            window.ordersChartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Orders',
                        data: data,
                        borderColor: '#10b981',
                        backgroundColor: gradient,
                        borderWidth: 2,
                        pointBackgroundColor: '#fff',
                        pointBorderColor: '#10b981',
                        pointBorderWidth: 2,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        fill: true,
                        tension: 0.4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: 'rgba(255,255,255,0.95)',
                            titleColor: '#1e293b',
                            bodyColor: '#334155',
                            borderColor: '#e2e8f0',
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
                                precision: 0 
                            },
                            grid: {
                                color: 'rgba(0,0,0,0.05)',
                                drawBorder: false
                            }
                        },
                        x: {
                            grid: { display: false }
                        }
                    }
                }
            });
        }
    }
});
