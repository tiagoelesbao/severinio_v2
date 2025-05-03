// Referências aos elementos
const operationSelect = document.getElementById("operation");
const fieldsEscalar = document.getElementById("fields-escalar");
const fieldsReduzir = document.getElementById("fields-reduzir");
const fieldsRealocar = document.getElementById("fields-realocar");
const scaleValueInput = document.getElementById("scale_value");
const minProfitInput = document.getElementById("min_profit");
const lowProfitInput = document.getElementById("low_profit");
const highProfitInput = document.getElementById("high_profit");
const reallocPctInput = document.getElementById("realloc_pct");
const reduceProfitLimitInput = document.getElementById("reduce_profit_limit");
const reducePctInput = document.getElementById("reduce_pct");
const dateRangeSelect = document.getElementById("date_range");
const customDatesSection = document.getElementById("custom-dates");
const startDateInput = document.getElementById("start_date");
const endDateInput = document.getElementById("end_date");
const startButton = document.getElementById("start-btn");
const logToggleBtn = document.getElementById("log-toggle-btn");
const logContainer = document.getElementById("log-container");

// Exibe ou oculta campos conforme operação
operationSelect.addEventListener("change", () => {
  const op = operationSelect.value;
  fieldsEscalar.style.display = "none";
  fieldsReduzir.style.display = "none";
  fieldsRealocar.style.display = "none";
  if (op === "escalar") {
    fieldsEscalar.style.display = "block";
  } else if (op === "reduzir") {
    fieldsReduzir.style.display = "block";
  } else if (op === "realocar") {
    fieldsRealocar.style.display = "block";
  }
});

// Exibe ou oculta datas personalizadas
dateRangeSelect.addEventListener("change", () => {
  if (dateRangeSelect.value === "custom") {
    customDatesSection.style.display = "block";
  } else {
    customDatesSection.style.display = "none";
  }
});

// Alterna visibilidade do painel de logs
function toggleLogs() {
  if (logContainer.style.display === "none" || logContainer.style.display === "") {
    logContainer.style.display = "block";
    logToggleBtn.textContent = "Ocultar Logs";
  } else {
    logContainer.style.display = "none";
    logToggleBtn.textContent = "Mostrar Logs";
  }
}
logToggleBtn.addEventListener("click", toggleLogs);

// Busca logs do servidor
function fetchLogs() {
  fetch("/logs")
    .then(response => response.json())
    .then(data => {
      logContainer.textContent = data.logs.join("\n");
      if (data.running) {
        setTimeout(fetchLogs, 1000);
      } else {
        startButton.disabled = false;
      }
    });
}

// Inicia o processo
startButton.addEventListener("click", () => {
  const payload = {
    operation: operationSelect.value,
    date_range: dateRangeSelect.value,
    start_date: startDateInput.value,
    end_date: endDateInput.value,
    scale_value: parseFloat(scaleValueInput.value) || 0,
    min_profit: parseFloat(minProfitInput.value) || 0,
    low_profit: parseFloat(lowProfitInput.value) || 0,
    high_profit: parseFloat(highProfitInput.value) || 0,
    realloc_pct: parseFloat(reallocPctInput.value) || 0,
    reduce_profit_limit: parseFloat(reduceProfitLimitInput.value) || 0,
    reduce_pct: parseFloat(reducePctInput.value) || 0
  };
  fetch("/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  })
    .then(response => response.json())
    .then(data => {
      if (data.error) {
        logContainer.style.display = "block";
        logContainer.innerHTML = "<span style='color:red'>" + data.error + "</span>";
      } else {
        startButton.disabled = true;
        logContainer.style.display = "block";
        logContainer.textContent = "Processo iniciado...\n";
        fetchLogs();
      }
    })
    .catch(err => {
      logContainer.style.display = "block";
      logContainer.innerHTML = "<span style='color:red'>Erro ao conectar ao servidor.</span>";
    });
});
