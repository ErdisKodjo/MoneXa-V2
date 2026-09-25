import 'package:flutter_bloc/flutter_bloc.dart';

import '../../data/payment_repository.dart';

abstract class PaymentsEvent {}

class LoadPaymentsEvent extends PaymentsEvent {
  LoadPaymentsEvent({this.status = 'TOUS'});
  final String status;
}

class ValidatePaymentActionSubmittedEvent extends PaymentsEvent {
  ValidatePaymentActionSubmittedEvent({
    required this.paymentId,
    required this.action,
    required this.currentFilterStatus,
  });
  final int paymentId;
  final String action;
  final String currentFilterStatus;
}

abstract class PaymentsState {}

class PaymentsInitial extends PaymentsState {}

class PaymentsLoading extends PaymentsState {}

class PaymentsLoaded extends PaymentsState {
  PaymentsLoaded({required this.payments, this.filter = 'TOUS'});
  final List<PaymentItem> payments;
  final String filter;
}

class PaymentsFailure extends PaymentsState {
  PaymentsFailure({required this.message});
  final String message;
}

class PaymentsBloc extends Bloc<PaymentsEvent, PaymentsState> {
  PaymentsBloc({required PaymentRepository repository})
      : _repository = repository,
        super(PaymentsInitial()) {
    on<LoadPaymentsEvent>(_onLoad);
    on<ValidatePaymentActionSubmittedEvent>(_onValidate);
  }

  final PaymentRepository _repository;

  Future<void> _onLoad(LoadPaymentsEvent event, Emitter<PaymentsState> emit) async {
    emit(PaymentsLoading());
    try {
      final payments = await _repository.getPayments(status: event.status);
      emit(PaymentsLoaded(payments: payments, filter: event.status));
    } catch (e) {
      emit(PaymentsFailure(message: e.toString().replaceFirst('Exception: ', '')));
    }
  }

  Future<void> _onValidate(
    ValidatePaymentActionSubmittedEvent event,
    Emitter<PaymentsState> emit,
  ) async {
    try {
      await _repository.validatePayment(event.paymentId, action: event.action);
      final payments = await _repository.getPayments(status: event.currentFilterStatus);
      emit(PaymentsLoaded(payments: payments, filter: event.currentFilterStatus));
    } catch (e) {
      emit(PaymentsFailure(message: e.toString().replaceFirst('Exception: ', '')));
    }
  }
}
