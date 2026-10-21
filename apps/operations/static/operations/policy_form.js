(() => {
  const form = document.querySelector('[data-policy-form]');
  if (!form) return;
  const mode = form.elements.namedItem('mode');
  const frequency = form.elements.namedItem('frequency');
  const period = form.elements.namedItem('period_strategy');
  if (!mode || !frequency || !period) return;

  form.querySelectorAll('input, select, textarea').forEach(control => {
    control.dataset.policyRequired = String(control.required);
  });

  const showGroup = (group, visible) => {
    group.hidden = !visible;
    group.querySelectorAll('input, select, textarea').forEach(control => {
      control.disabled = !visible;
      control.required = visible && control.dataset.policyRequired === 'true';
    });
  };

  const update = () => {
    const automatic = mode.value !== 'manual';
    form.querySelectorAll('[data-policy-automatic]').forEach(group => showGroup(group, automatic));
    form.querySelectorAll('[data-policy-frequency]').forEach(group => {
      showGroup(group, automatic && group.dataset.policyFrequency === frequency.value);
    });
    form.querySelectorAll('[data-policy-period]').forEach(group => {
      showGroup(group, automatic && group.dataset.policyPeriod === period.value);
    });
    const manualNote = form.querySelector('[data-policy-manual]');
    if (manualNote) manualNote.hidden = automatic;
    form.elements.namedItem('scheduled_time').required = automatic;
  };

  [mode, frequency, period].forEach(control => control.addEventListener('change', update));
  update();
})();
