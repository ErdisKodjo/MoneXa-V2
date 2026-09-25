import 'package:flutter_bloc/flutter_bloc.dart';

import '../../data/auth_repository.dart';

abstract class AuthEvent {}

class CheckAuthStatusEvent extends AuthEvent {}

class LoginSubmittedEvent extends AuthEvent {
  LoginSubmittedEvent({required this.email, required this.password});
  final String email;
  final String password;
}

class LogoutRequestedEvent extends AuthEvent {}

abstract class AuthState {}

class AuthInitial extends AuthState {}

class AuthLoading extends AuthState {}

class Unauthenticated extends AuthState {}

class Authenticated extends AuthState {
  Authenticated({required this.user});
  final UserModel user;
}

class AuthFailure extends AuthState {
  AuthFailure({required this.message});
  final String message;
}

class AuthBloc extends Bloc<AuthEvent, AuthState> {
  AuthBloc({required AuthRepository repository})
      : _repository = repository,
        super(AuthInitial()) {
    on<CheckAuthStatusEvent>(_onCheck);
    on<LoginSubmittedEvent>(_onLogin);
    on<LogoutRequestedEvent>(_onLogout);
  }

  final AuthRepository _repository;

  Future<void> _onCheck(CheckAuthStatusEvent event, Emitter<AuthState> emit) async {
    emit(AuthLoading());
    try {
      final user = await _repository.getStoredUser();
      if (user == null) {
        emit(Unauthenticated());
      } else {
        emit(Authenticated(user: user));
      }
    } catch (_) {
      emit(Unauthenticated());
    }
  }

  Future<void> _onLogin(LoginSubmittedEvent event, Emitter<AuthState> emit) async {
    emit(AuthLoading());
    try {
      final user = await _repository.login(email: event.email, password: event.password);
      emit(Authenticated(user: user));
    } catch (e) {
      emit(AuthFailure(message: e.toString().replaceFirst('Exception: ', '')));
    }
  }

  Future<void> _onLogout(LogoutRequestedEvent event, Emitter<AuthState> emit) async {
    emit(AuthLoading());
    await _repository.logout();
    emit(Unauthenticated());
  }

  @override
  Future<void> close() {
    super.close();
    return Future<void>.value();
  }
}
