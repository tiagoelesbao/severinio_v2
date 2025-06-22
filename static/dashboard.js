// ========== ADICIONE ESTAS DUAS FUNÇÕES ==========

// Função para carregar status das contas
function loadAccountStatus() {
  fetch("/account_status")
    .then(response => response.json())
    .then(data => {
      const statusElement = document.getElementById("account-status");
      if (statusElement && data.total_accounts > 0) {
        statusElement.innerHTML = `
          <div style="background: rgba(23, 162, 184, 0.2); border: 1px solid #17a2b8; color: #17a2b8; padding: 0.75rem; border-radius: 4px; margin: 1rem;">
            <strong>Status das Contas:</strong><br>
            Total de contas: ${data.total_accounts}<br>
            Contas CBO: ${data.cbo_accounts}<br>
            Contas ABO: ${data.abo_accounts}
            ${data.abo_accounts > 0 ? `<br><small>ABO: ${data.abo_list.join(', ')}</small>` : ''}
          </div>
        `;
      }
    })
    .catch(err => {
      console.error("Erro ao carregar status das contas:", err);
    });
}

// Carregar status quando a página carregar
document.addEventListener("DOMContentLoaded", () => {
  loadAccountStatus();
});

// ========== FIM DAS ADIÇÕES ==========

// RESTO DO SEU CÓDIGO JAVASCRIPT EXISTENTE...