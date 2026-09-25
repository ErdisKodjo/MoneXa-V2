class AppConstants {
  AppConstants._();

  static const String appName = 'MoneXa';
  static const String apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://10.0.2.2:8000',
  );

  static const String roleGerant = 'GERANT';
  static const String roleComptable = 'COMPTABLE';
  static const String roleCaissier = 'CAISSIER';

  static const String emailGerant = 'gerant@monexa.tg';
  static const String emailComptable = 'comptable@monexa.tg';
  static const String emailCaissier = 'caissier@monexa.tg';
  static const String demoPassword = 'Monexa2026!';

  static const String statusTous = 'TOUS';
  static const String statusAValider = 'A_VALIDER';
  static const String statusReconcilie = 'RECONCILIE';
  static const String statusAnomalie = 'ANOMALIE';
  static const String statusNonRattache = 'NON_RATTACHE';
}
