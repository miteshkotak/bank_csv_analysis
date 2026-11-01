// Renders the Tax Analysis page from window.TAX_DATA (built by compute_corporate_tax in corporate_tax.py)
(() => {
    const D = window.TAX_DATA;

    const formatMoney = (amount) =>
        new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(amount);
    const esc = (value) => String(value).replace(/[&<>"']/g, (c) =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const fmtDate = (iso) => iso
        ? new Date(iso).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
        : '—';
    const setText = (id, text) => { document.getElementById(id).textContent = text; };
    const withFy = (url) => `${url}?fy=${encodeURIComponent(D.fy)}`;

    function renderHeader() {
        setText('gen-date', 'Generated: ' + new Date().toLocaleDateString());
        setText('period-label', `${D.period} (AY ${D.ay})`);
        setText('regime-label', `· ${D.regime.name} @ ${D.regime.effective_rate.toFixed(3)}%`);

        const select = document.getElementById('fy-select');
        select.innerHTML = D.fys.map(fy => `<option value="${esc(fy)}" ${fy === D.fy ? 'selected' : ''}>FY ${esc(fy)}</option>`).join('');
        select.addEventListener('change', () => { window.location = `/analyze?fy=${encodeURIComponent(select.value)}`; });
        document.getElementById('fd-report-link').href = withFy('/analyze/fd-report.xlsx');
        document.querySelectorAll('nav a[href="/"]').forEach(a => { a.href = withFy('/'); });
    }

    function renderSummary() {
        setText('total-income', formatMoney(D.income.total));
        setText('deductible-expenses', formatMoney(D.expenses.deductible));
        setText('taxable-income', formatMoney(D.computation.total_income));
        setText('estimated-tax', formatMoney(D.computation.tax));
        setText('business-income', formatMoney(D.income.business));
        setText('fd-interest', formatMoney(D.income.fd_interest));
    }

    function exclusionList(id, items, emptyText) {
        document.getElementById(id).innerHTML = items.length
            ? items.map(e => `
                <li class="flex justify-between gap-4 px-3 py-2 bg-slate-800/30 rounded-lg">
                    <span class="text-slate-300">${esc(e.reason)} <span class="text-slate-500 text-xs">(${e.count})</span></span>
                    <span class="font-mono text-slate-400">${formatMoney(e.amount)}</span>
                </li>`).join('')
            : `<li class="text-slate-500 text-sm">${emptyText}</li>`;
    }

    function renderReconciliation() {
        const rec = D.reconciliation;
        if (!rec) return;
        document.getElementById('recon-panel').classList.remove('hidden');
        const status = document.getElementById('recon-status');
        const matched = rec.status === 'match';
        status.textContent = matched ? `Matches within ${rec.tolerance_pct}%` : 'Review rules: gap above tolerance';
        status.className += matched ? ' bg-emerald-500/20 text-emerald-300' : ' bg-amber-500/20 text-amber-300';
        document.getElementById('recon-tbody').innerHTML = rec.rows.map(r => `
            <tr>
                <td class="px-4 py-3 text-slate-200">${esc(r.label)}</td>
                <td class="px-4 py-3 text-right font-mono">${formatMoney(r.engine)}</td>
                <td class="px-4 py-3 text-right font-mono">${formatMoney(r.actual)}</td>
                <td class="px-4 py-3 text-right font-mono ${Math.abs(r.gap_pct) <= rec.tolerance_pct ? 'text-emerald-400' : 'text-amber-400'}">
                    ${r.gap >= 0 ? '+' : '−'}${formatMoney(Math.abs(r.gap))} (${r.gap_pct.toFixed(2)}%)
                </td>
            </tr>`).join('');
    }

    function renderComputation() {
        const c = D.computation, r = D.regime, i = D.interest;
        const row = (label, value, cls = '') => `
            <div class="flex justify-between items-center p-3 bg-slate-800/20 rounded-lg ${cls}">
                <span class="text-slate-300">${label}</span><span class="font-mono text-slate-100">${value}</span>
            </div>`;
        const sat = i['234B_months'] ? ` (${i['234B_months']} months to ${fmtDate(i.self_assessment_date)})` : '';
        document.getElementById('computation-rows').innerHTML = [
            row('Total income (business + FD interest)', formatMoney(D.income.total)),
            row('Less: deductible expenses', '− ' + formatMoney(D.expenses.deductible), 'border-l-4 border-blue-500'),
            row('Taxable income (rounded to ₹10)', formatMoney(c.total_income), 'border border-purple-500/30'),
            row(`Tax @ ${r.base_rate}%`, formatMoney(c.base_tax)),
            row(`Surcharge @ ${r.surcharge}%`, formatMoney(c.surcharge)),
            row(`Health & education cess @ ${r.cess}%`, formatMoney(c.cess)),
            row('Total tax', formatMoney(c.tax), 'border border-orange-500/30 font-semibold'),
            row('Less: TDS on FD interest', '− ' + formatMoney(D.credits.tds)),
            row('Less: advance tax paid', '− ' + formatMoney(D.credits.advance_tax)),
            row('Add: interest u/s 234C (deferred instalments)', formatMoney(i['234C'])),
            row('Add: interest u/s 234B' + sat, formatMoney(i['234B'])),
        ].join('');

        const payable = D.payable;
        const glow = document.getElementById('refund-glow');
        setText('refund-label', payable > 0 ? 'Tax Payable' : 'Tax Refund');
        setText('refund-caption', payable > 0 ? 'Self-assessment tax due' : 'Expected');
        document.getElementById('refund-label').classList.add(payable > 0 ? 'text-red-400' : 'text-emerald-400');
        setText('refund-amount', formatMoney(Math.abs(payable)));
        if (payable > 0) {
            glow.classList.remove('from-emerald-500/20', 'to-blue-500/20');
            glow.classList.add('from-red-500/20', 'to-orange-500/20');
        }
    }

    function renderFd() {
        const FD = D.fd_summary, t = FD.totals;
        setText('fd-subtitle', `${t.deposit_count} fixed deposit(s) found in statement`);
        setText('fd-gross', formatMoney(t.gross_interest));
        setText('fd-tds', formatMoney(t.tds));
        setText('fd-tds-rate', `Effective rate ${t.effective_tds_rate.toFixed(1)}%`);
        setText('fd-net', formatMoney(t.net_interest));
        setText('fd-principal', formatMoney(t.principal_booked));
        setText('fd-returned', formatMoney(t.principal_returned));

        document.getElementById('fd-tbody').innerHTML = FD.deposits.length
            ? FD.deposits.map(d => `
                <tr class="hover:bg-slate-800/30 transition-colors">
                    <td class="px-4 py-3 font-mono text-slate-200">${esc(d.fd_number)}</td>
                    <td class="px-4 py-3">${fmtDate(d.booked_on)}</td>
                    <td class="px-4 py-3 text-right font-mono">${d.principal ? formatMoney(d.principal) : '—'}</td>
                    <td class="px-4 py-3 text-right font-mono text-emerald-400">${formatMoney(d.interest)}</td>
                    <td class="px-4 py-3 text-right font-mono text-red-400">${formatMoney(d.tds)}</td>
                    <td class="px-4 py-3 text-right font-mono text-teal-400">${formatMoney(d.net_interest)}</td>
                </tr>`).join('')
            : '<tr><td colspan="6" class="px-4 py-6 text-center text-slate-500">No FD transactions found</td></tr>';

        if (!FD.monthly.length) {
            document.getElementById('fdMonthlyChart').parentElement.innerHTML =
                '<p class="h-full flex items-center justify-center text-sm text-slate-500">No FD interest this year</p>';
            return;
        }
        new Chart(document.getElementById('fdMonthlyChart'), {
            type: 'bar',
            data: {
                labels: FD.monthly.map(m => new Date(m.month + '-01').toLocaleDateString('en-IN', { month: 'short', year: '2-digit' })),
                datasets: [
                    { label: 'Interest', data: FD.monthly.map(m => m.interest), backgroundColor: '#14b8a6', borderRadius: 4 },
                    { label: 'TDS', data: FD.monthly.map(m => m.tds), backgroundColor: '#ef4444', borderRadius: 4 },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: { grid: { color: '#334155' }, ticks: { color: '#94a3b8', callback: v => '₹' + (v / 1000).toFixed(0) + 'K' } },
                    x: { grid: { display: false }, ticks: { color: '#94a3b8', font: { size: 11 } } },
                },
                plugins: {
                    legend: { position: 'bottom', labels: { color: '#94a3b8' } },
                    tooltip: { callbacks: { label: c => `${c.dataset.label}: ${formatMoney(c.raw)}` } },
                },
            },
        });
    }

    function renderExpenses() {
        const cats = D.expenses.by_category;
        const deductible = cats.filter(c => c.Deductible > 0).sort((a, b) => b.Deductible - a.Deductible);
        const palette = ['#3b82f6', '#8b5cf6', '#10b981', '#f59e0b', '#ef4444', '#06b6d4', '#ec4899', '#84cc16', '#64748b'];
        new Chart(document.getElementById('expenseDistChart'), {
            type: 'doughnut',
            data: {
                labels: deductible.map(c => c.Category),
                datasets: [{ data: deductible.map(c => c.Deductible), backgroundColor: palette, borderColor: '#1e293b', borderWidth: 3 }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'bottom', labels: { color: '#94a3b8', padding: 12, font: { size: 12 } } },
                    tooltip: { callbacks: { label: c => `${c.label}: ${formatMoney(c.raw)}` } },
                },
            },
        });

        const badge = (c) => {
            if (c.Deductible >= c.Amount - 0.5) return '<span class="px-3 py-1 rounded-full bg-blue-500/20 text-blue-400 text-xs font-medium">Yes</span>';
            if (c.Deductible > 0) return '<span class="px-3 py-1 rounded-full bg-amber-500/20 text-amber-300 text-xs font-medium">Partial</span>';
            return '<span class="px-3 py-1 rounded-full bg-slate-700/50 text-slate-400 text-xs font-medium">No</span>';
        };
        document.getElementById('category-tbody').innerHTML = cats.map(c => `
            <tr class="hover:bg-slate-800/30 transition-colors">
                <td class="px-6 py-4 font-medium text-slate-200">${esc(c.Category)}</td>
                <td class="px-6 py-4 text-right font-mono text-slate-300">${formatMoney(c.Amount)}</td>
                <td class="px-6 py-4 text-right font-mono text-slate-300">${formatMoney(c.Deductible)}</td>
                <td class="px-6 py-4 text-center">${badge(c)}</td>
            </tr>`).join('');
    }

    function renderPlannerAndChallans() {
        const statusBadge = {
            paid: '<span class="px-2 py-1 rounded-full bg-emerald-500/20 text-emerald-300 text-xs">Paid</span>',
            short: '<span class="px-2 py-1 rounded-full bg-red-500/20 text-red-300 text-xs">Short</span>',
            upcoming: '<span class="px-2 py-1 rounded-full bg-slate-700/50 text-slate-300 text-xs">Upcoming</span>',
        };
        document.getElementById('planner-tbody').innerHTML = D.planner.map(p => `
            <tr>
                <td class="px-4 py-3 text-slate-200">${fmtDate(p.due)} <span class="text-slate-500 text-xs">(${p.percent}%)</span></td>
                <td class="px-4 py-3 text-right font-mono">${formatMoney(p.required)}</td>
                <td class="px-4 py-3 text-right font-mono">${formatMoney(p.paid_by)}</td>
                <td class="px-4 py-3 text-right font-mono ${p.shortfall > 0 ? 'text-red-400' : ''}">${formatMoney(p.shortfall)}</td>
                <td class="px-4 py-3 text-center">${statusBadge[p.status]}</td>
            </tr>`).join('');

        const kindLabel = { advance: 'Advance tax', self_assessment: 'Self-assessment tax' };
        document.getElementById('challan-tbody').innerHTML = D.challans.length
            ? D.challans.map(c => {
                const counts = c.kind === 'advance' && c.ay === D.ay;
                return `
                <tr>
                    <td class="px-4 py-3 text-slate-200">${fmtDate(c.date)}</td>
                    <td class="px-4 py-3 text-right font-mono">${formatMoney(c.amount)}</td>
                    <td class="px-4 py-3">
                        <span class="${counts ? 'text-emerald-300' : 'text-slate-400'}">${kindLabel[c.kind]} · AY ${esc(c.ay)}</span>
                        <span class="text-xs text-slate-500">${c.auto ? '(auto)' : '(set in Admin)'}</span>
                    </td>
                </tr>`;
            }).join('')
            : '<tr><td colspan="3" class="px-4 py-6 text-center text-slate-500">No CBDT payments in this statement</td></tr>';
    }

    function renderExcludedTransactions() {
        const rows = D.excluded_transactions;
        setText('excluded-count', `(${rows.length})`);
        document.getElementById('excluded-tbody').innerHTML = rows.map(r => `
            <tr>
                <td class="px-6 py-3 whitespace-nowrap">${esc(r.date)}</td>
                <td class="px-6 py-3 text-slate-300">${esc(r.narration)}</td>
                <td class="px-6 py-3">${esc(r.reason)}</td>
                <td class="px-6 py-3 text-right font-mono">${formatMoney(r.amount)}</td>
            </tr>`).join('');
    }

    document.addEventListener('DOMContentLoaded', () => {
        renderHeader();
        renderSummary();
        exclusionList('income-excluded', D.income.excluded, 'None');
        exclusionList('expense-excluded', D.expenses.excluded, 'None');
        renderReconciliation();
        renderComputation();
        renderFd();
        renderExpenses();
        renderPlannerAndChallans();
        renderExcludedTransactions();
        document.querySelectorAll('.stat-card').forEach((card, index) => {
            setTimeout(() => card.classList.add('animate-slide-in'), index * 100);
        });
    });
})();
